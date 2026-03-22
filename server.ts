import express from "express";
import { createServer as createViteServer } from "vite";
import path from "path";
import { fileURLToPath } from "url";

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
  app.get("/api/extensions", (req, res) => {
    res.json(extensions);
  });

  app.get("/api/updates", (req, res) => {
    res.json(updates);
  });

  app.post("/api/refresh-updates", (req, res) => {
    // Simulate a refresh delay
    setTimeout(() => {
      res.json({ status: "success", message: "Updates refreshed" });
    }, 2000);
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

  app.get("/api/search", (req, res) => {
    const q = (req.query.q as string || "").toLowerCase();
    const mockPackages = [
      { name: "vlc", description: "Multimedia player and framework" },
      { name: "obs-studio", description: "Software for video recording and live streaming" },
      { name: "gimp", description: "GNU Image Manipulation Program" },
      { name: "inkscape", description: "Vector graphics editor" },
      { name: "neovim", description: "Hyperextensible Vim-based text editor" },
      { name: "htop", description: "Interactive process viewer" },
      { name: "fastfetch", description: "A fetch tool for system information" },
    ];
    const results = mockPackages.filter(p => 
      p.name.toLowerCase().includes(q) || p.description.toLowerCase().includes(q)
    );
    res.json(results);
  });

  app.get("/api/doctor", (req, res) => {
    res.json({
      status: "healthy",
      checks: [
        { name: "Daemon Connection", status: "ok", message: "Socket reachable at /run/sysext-creator/sysext-creator.sock" },
        { name: "Toolbox Container", status: "ok", message: "Container 'sysext-builder' is running" },
        { name: "Systemd-Sysext", status: "ok", message: "Service is active and refreshing" },
        { name: "Tmpfiles.d Sync", status: "ok", message: "Sync script is working correctly" },
        { name: "Disk Space", status: "ok", message: "12.4 GB available in /var/lib/extensions" },
      ]
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
