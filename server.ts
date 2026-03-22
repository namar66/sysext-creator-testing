import express from 'express';
import { createServer as createViteServer } from 'vite';
import path from 'path';
import { exec } from 'child_process';
import { promisify } from 'util';

const execAsync = promisify(exec);
const app = express();
const PORT = 3000;

app.use(express.json());

// --- API ROUTES ---

// Mock data for now, in "ostry release" these will call real system commands
app.get('/api/extensions', (req, res) => {
  res.json([
    { name: 'mc', version: '4.8.31-1.fc43', packages: 'mc, slang, gpm-libs' },
    { name: 'htop', version: '3.3.0-4.fc43', packages: 'htop' },
    { name: 'fastfetch', version: '2.34.0-1.fc43', packages: 'fastfetch, yyjson' }
  ]);
});

app.get('/api/updates', (req, res) => {
  res.json([
    { name: 'mc', current: '4.8.31-1.fc43', latest: '4.8.31-2.fc43' }
  ]);
});

app.get('/api/doctor', async (req, res) => {
  try {
    // Real call to sysext-doctor.py
    const { stdout } = await execAsync('sudo python3 /sysext-doctor.py');
    
    // Parse doctor output (simplified for now)
    const lines = stdout.split('\n');
    const checks = lines
      .filter(l => l.includes('[ OK ]') || l.includes('[FAIL]') || l.includes('[WARN]'))
      .map(l => {
        const status = l.includes('[ OK ]') ? 'ok' : 'error';
        const message = l.split('] ')[1];
        const name = message.split(' ')[0];
        return { name, status, message };
      });

    res.json({
      status: checks.some(c => c.status === 'error') ? 'unhealthy' : 'healthy',
      checks: checks.length > 0 ? checks : [
        { name: 'System', status: 'ok', message: 'No critical collisions detected.' }
      ]
    });
  } catch (e) {
    res.json({
      status: 'error',
      checks: [{ name: 'Doctor', status: 'error', message: 'Failed to run sysext-doctor.py' }]
    });
  }
});

app.post('/api/refresh-updates', (req, res) => {
  res.json({ status: 'ok' });
});

app.post('/api/update-all', (req, res) => {
  res.json({ status: 'ok' });
});

app.get('/api/search', (req, res) => {
  const q = req.query.q as string;
  res.json([
    { name: q || 'example-pkg', description: 'A sample package from Fedora repositories' },
    { name: 'vim-enhanced', description: 'A version of the VIM editor which includes recent enhancements' }
  ]);
});

app.post('/api/remove', (req, res) => {
  res.json({ status: 'ok' });
});

// --- VITE MIDDLEWARE ---

async function startServer() {
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
