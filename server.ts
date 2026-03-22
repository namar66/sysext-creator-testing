import express from 'express';
import { createServer as createViteServer } from 'vite';
import path from 'path';
import { exec } from 'child_process';
import { promisify } from 'util';
import net from 'net';
import fs from 'fs';

const execAsync = promisify(exec);
const app = express();
const PORT = 3000;
const SOCKET_PATH = '/run/sysext-creator.sock';

app.use(express.json());

// --- SECURE DAEMON COMMUNICATION ---

function callDaemon(method: string, params: any = {}): Promise<any> {
  return new Promise((resolve, reject) => {
    const client = net.createConnection(SOCKET_PATH);
    let responseData = '';

    client.on('connect', () => {
      // Send with null byte delimiter
      client.write(JSON.stringify({ method, params }) + '\0');
    });

    client.on('data', (data) => {
      responseData += data.toString();
      // If we see the null byte, we can close early or just wait for 'end'
      if (responseData.includes('\0')) {
        client.end();
      }
    });

    client.on('end', () => {
      try {
        const msg = responseData.split('\0')[0];
        const resp = JSON.parse(msg);
        // Handle Varlink-style parameters or direct status
        resolve(resp.parameters || resp);
      } catch (e) {
        reject(new Error('Invalid response from daemon'));
      }
    });

    client.on('error', (err) => {
      reject(err);
    });
  });
}

// Helper to validate inputs (alphanumeric + some safe chars)
function isValidInput(input: string): boolean {
  return /^[a-zA-Z0-9._+-]+$/.test(input);
}

// --- API ROUTES ---

app.get('/api/extensions', async (req, res) => {
  try {
    const result = await callDaemon('ListExtensions');
    res.json(result.extensions || []);
  } catch (e) {
    res.json([]);
  }
});

app.get('/api/updates', (req, res) => {
  res.json([]); 
});

app.get('/api/doctor', async (req, res) => {
  try {
    const result = await callDaemon('doctor');
    const lines = result.output.split('\n');
    const checks = lines
      .filter((l: string) => l.includes('[ OK ]') || l.includes('[FAIL]') || l.includes('[WARN]'))
      .map((l: string) => {
        const status = l.includes('[ OK ]') ? 'ok' : 'error';
        const parts = l.split('] ');
        const message = parts.length > 1 ? parts[1] : l;
        
        // Try to extract a meaningful name
        let name = 'System';
        if (message.startsWith('/')) {
          name = message.split(' ')[0];
        } else if (message.includes('Collision:')) {
          name = 'Collision';
        } else if (message.includes('No cross-extension')) {
          name = 'Cross-Extension';
        } else if (message.includes('extension-release')) {
          name = 'Release';
        }
        
        return { name, status, message };
      });

    res.json({
      status: checks.some((c: any) => c.status === 'error') ? 'unhealthy' : 'healthy',
      checks: checks.length > 0 ? checks : [
        { name: 'System', status: 'ok', message: 'No critical issues detected.' }
      ]
    });
  } catch (e) {
    res.json({
      status: 'error',
      checks: [{ name: 'Doctor', status: 'error', message: 'Failed to communicate with daemon' }]
    });
  }
});

app.post('/api/refresh-updates', (req, res) => {
  res.json({ status: 'ok' });
});

app.post('/api/update-all', async (req, res) => {
  res.json({ status: 'queued' });
});

app.get('/api/search', async (req, res) => {
  const q = req.query.q as string;
  if (!q || !isValidInput(q)) return res.json([]);
  
  try {
    const result = await callDaemon('search', { q });
    res.json(result.results || []);
  } catch (e) {
    res.json([]);
  }
});

app.post('/api/remove', async (req, res) => {
  const { name } = req.body;
  if (!name || !isValidInput(name)) {
    return res.status(400).json({ error: 'Invalid name' });
  }

  try {
    const result = await callDaemon('remove', { name });
    if (result.status === 'ok') {
      res.json({ status: 'ok' });
    } else {
      res.status(500).json({ error: result.message });
    }
  } catch (e) {
    res.status(500).json({ error: 'Failed to communicate with daemon' });
  }
});

// --- VITE MIDDLEWARE ---

async function startServer() {
  // Ensure daemon is running (in a real system, this is handled by systemd)
  // We try to kill any existing daemon to ensure we use the latest code
  try {
    await execAsync('sudo pkill -f sysext-daemon.py');
    // Wait a bit for the socket to be cleaned up
    await new Promise(resolve => setTimeout(resolve, 500));
  } catch (e) {
    // pkill fails if no process found, which is fine
  }

  if (!fs.existsSync(SOCKET_PATH)) {
    console.log('Starting sysext-daemon...');
    exec('sudo python3 /sysext-daemon.py &');
  }

  if (process.env.NODE_ENV !== 'production') {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: 'spa',
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), 'dist');
    app.use(express.static(distPath));
    app.get('*', (req, res) => {
      res.sendFile(path.join(distPath, 'index.html'));
    });
  }

  app.listen(PORT, '0.0.0.0', () => {
    console.log(`Server running on http://localhost:${PORT}`);
  });
}

startServer();
