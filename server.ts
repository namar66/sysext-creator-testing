import express from "express";
import { createServer as createViteServer } from "vite";
import path from "path";
import { fileURLToPath } from "url";
import { exec } from "child_process";
import { promisify } from "util";
import fs from "fs";

const execAsync = promisify(exec);

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

async function startServer() {
  const app = express();
  const PORT = 3000;

  app.use(express.json());

  // Mock Data
  let extensions = [
    { name: "sysext-creator-deps", version: "1.9.1-1.fc43", packages: "N/A" },
    { name: "distrobox", version: "1.8.2.4-1.fc43", packages: "N/A" },
    { name: "mc", version: "1:4.8.33-2.fc43", packages: "N/A" },
    { name: "krusader", version: "2.9.0-3.fc43", packages: "N/A" },
    { name: "kate", version: "25.12.3-1.fc43", packages: "N/A" },
  ];

  let updates = [
    { name: "distrobox", current: "1.8.2.4-1.fc43", latest: "1.8.3.0-1.fc43" },
    { name: "mc", current: "1:4.8.33-2.fc43", latest: "1:4.8.34-1.fc43" },
  ];

  // API Routes
  app.get("/api/extensions", async (req, res) => {
    try {
      // 1. Try to ask the daemon directly via CLI (which should talk to the socket)
      try {
        const { stdout: daemonOutput } = await execAsync("sysext-creator list --json 2>/dev/null || echo ''");
        if (daemonOutput.trim()) {
          const daemonExtensions = JSON.parse(daemonOutput);
          if (Array.isArray(daemonExtensions)) {
            return res.json(daemonExtensions.map(ext => ({
              ...ext,
              mode: "live"
            })));
          }
        }
      } catch (e) {
        // Fallback to manual file listing if daemon query fails
      }

      // 2. Fallback: list files in /var/lib/extensions
      const { stdout } = await execAsync("ls /var/lib/extensions || echo ''");
      const files = stdout.split("\n").filter(f => f.trim() !== "" && (f.endsWith(".raw") || f.endsWith(".img")));
      
      if (files.length === 0) {
        return res.json(extensions.map(e => ({ ...e, mode: "demo" })));
      }

      const realExtensions = await Promise.all(files.map(async (f) => {
        const fullName = f.replace(".raw", "").replace(".img", "");
        let name = fullName;
        let version = "installed";
        let packages = "N/A";

        // Try to parse name-version from filename
        const parts = fullName.split("-");
        if (parts.length > 1) {
          const possibleVersion = parts[parts.length - 1];
          if (/[0-9]/.test(possibleVersion)) {
            version = parts.pop() || "installed";
            name = parts.join("-");
          }
        }

        // Ask daemon for info about this specific extension
        try {
          const { stdout: info } = await execAsync(`sysext-creator info ${fullName} --json 2>/dev/null || echo ''`);
          if (info.trim()) {
            const metadata = JSON.parse(info);
            if (metadata.version) version = metadata.version;
            if (metadata.packages) packages = metadata.packages.join(", ");
          } else {
            // Fallback: try to get version from rpm if we can guess the package name
            const { stdout: rpmVer } = await execAsync(`rpm -q --qf "%{VERSION}-%{RELEASE}" ${name} 2>/dev/null || echo ''`);
            if (rpmVer.trim() && !rpmVer.includes("not installed")) {
              version = rpmVer.trim();
            }
          }
        } catch (e) {
          // Ignore errors
        }

        return {
          name,
          version,
          packages,
          mode: "live"
        };
      }));

      res.json(realExtensions);
    } catch (e) {
      res.json(extensions.map(e => ({ ...e, mode: "demo" })));
    }
  });

  app.get("/api/updates", async (req, res) => {
    try {
      // For Atomic/Silverblue: rpm-ostree upgrade --check
      // For standard Fedora: dnf check-update
      // We'll try dnf first as it's more common for sysext building
      const { stdout } = await execAsync("dnf check-update --quiet || echo ''");
      const lines = stdout.split("\n").filter(l => l.trim() !== "");
      
      // Basic parsing of dnf check-update output
      const realUpdates = lines
        .map(line => {
          const parts = line.split(/\s+/);
          if (parts.length >= 3) {
            return {
              name: parts[0].split(".")[0],
              current: "installed",
              latest: parts[1],
              mode: "live"
            };
          }
          return null;
        })
        .filter(u => u !== null);

      if (realUpdates.length === 0) {
        return res.json(updates.map(u => ({ ...u, mode: "demo" })));
      }
      res.json(realUpdates);
    } catch (e) {
      res.json(updates.map(u => ({ ...u, mode: "demo" })));
    }
  });

  app.post("/api/refresh-updates", async (req, res) => {
    try {
      await execAsync("dnf makecache --refresh || true");
      res.json({ status: "success", message: "Metadata refreshed" });
    } catch (e) {
      res.status(500).json({ status: "error", message: "Failed to refresh metadata" });
    }
  });

  app.post("/api/update-all", (req, res) => {
    // Simulate updating
    setTimeout(() => {
      extensions = extensions.map(ext => {
        const update = updates.find(u => u.name === ext.name);
        return update ? { ...ext, version: update.latest } : ext;
      });
      updates = [];
      res.json({ status: "success" });
    }, 3000);
  });

  app.get("/api/search", async (req, res) => {
    const q = (req.query.q as string || "").toLowerCase();
    if (!q) return res.json([]);

    try {
      // Try real dnf search
      const { stdout } = await execAsync(`dnf search ${q} --quiet || echo ''`);
      const lines = stdout.split("\n").filter(l => l.trim() !== "" && l.includes(" : "));
      
      const results = lines.map(line => {
        const [namePart, desc] = line.split(" : ");
        return {
          name: namePart.split(".")[0].trim(),
          description: desc.trim(),
          mode: "live"
        };
      });

      if (results.length > 0) {
        return res.json(results);
      }

      // Fallback to mock if no results or dnf fails
      const mockPackages = [
        { name: "vlc", description: "Multimedia player and framework" },
        { name: "obs-studio", description: "Software for video recording and live streaming" },
        { name: "gimp", description: "GNU Image Manipulation Program" },
        { name: "inkscape", description: "Vector graphics editor" },
        { name: "neovim", description: "Hyperextensible Vim-based text editor" },
        { name: "htop", description: "Interactive process viewer" },
        { name: "fastfetch", description: "A fetch tool for system information" },
      ];
      const filteredMock = mockPackages.filter(p => 
        p.name.toLowerCase().includes(q) || p.description.toLowerCase().includes(q)
      );
      res.json(filteredMock.map(p => ({ ...p, mode: "demo" })));
    } catch (e) {
      res.json([]);
    }
  });

  app.get("/api/doctor", async (req, res) => {
    const checks = [
      { name: "Daemon Connection", status: "error", message: "Socket not found" },
      { name: "Toolbox Container", status: "error", message: "Container not found" },
      { name: "Systemd-Sysext", status: "error", message: "Service not active" },
      { name: "Disk Space", status: "ok", message: "Checking..." },
    ];

    try {
      // Check Socket
      const socketPath = "/run/sysext-creator/sysext-creator.sock";
      if (fs.existsSync(socketPath)) {
        checks[0].status = "ok";
        checks[0].message = `Socket reachable at ${socketPath}`;
      } else {
        checks[0].message = `Socket not found at ${socketPath}`;
      }

      // Check Toolbox Container
      try {
        const { stdout: podman } = await execAsync("podman ps --filter name=sysext-builder --format '{{.Status}}' || echo ''");
        if (podman.trim()) {
          checks[1].status = "ok";
          checks[1].message = `Container 'sysext-builder' is ${podman.trim()}`;
        } else {
          checks[1].message = "Container 'sysext-builder' not running";
        }
      } catch (e) {
        checks[1].message = "Podman not available or failed";
      }

      // Check Systemd Service
      const { stdout: sysextStatus } = await execAsync("systemctl is-active systemd-sysext || echo 'inactive'");
      checks[2].status = sysextStatus.trim() === "active" ? "ok" : "error";
      checks[2].message = `Service is ${sysextStatus.trim()}`;

      // Check Disk Space
      const { stdout: df } = await execAsync("df -h /var/lib/extensions | tail -1 | awk '{print $4}' || echo 'N/A'");
      checks[3].message = `${df.trim()} available in /var/lib/extensions`;
      checks[3].status = df.trim() !== "N/A" ? "ok" : "error";
    } catch (e) {
      // Keep defaults if commands fail
    }

    res.json({
      status: checks.every(c => c.status === "ok") ? "healthy" : "warning",
      checks
    });
  });

  app.post("/api/remove", (req, res) => {
    const { name } = req.body;
    extensions = extensions.filter(e => e.name !== name);
    res.json({ status: "success" });
  });

  // Vite middleware for development
  if (process.env.NODE_ENV !== "production") {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: "spa",
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), "dist");
    app.use(express.static(distPath));
    app.get("*", (req, res) => {
      res.sendFile(path.join(distPath, "index.html"));
    });
  }

  app.listen(PORT, "0.0.0.0", () => {
    console.log(`Server running on http://localhost:${PORT}`);
  });
}

startServer();
