import React, { useState, useEffect } from 'react';
import { 
  Package, 
  RefreshCw, 
  Search as SearchIcon, 
  Stethoscope, 
  Trash2, 
  Download, 
  CheckCircle2, 
  AlertCircle, 
  Activity,
  Terminal
} from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';

type Tab = 'extensions' | 'update' | 'search' | 'doctor';

interface Extension {
  name: string;
  version: string;
  packages: string;
}

interface Update {
  name: string;
  current: string;
  latest: string;
}

interface SearchResult {
  name: string;
  description: string;
}

interface DoctorCheck {
  name: string;
  status: 'ok' | 'error';
  message: string;
}

export default function App() {
  const [activeTab, setActiveTab] = useState<Tab>('extensions');
  const [extensions, setExtensions] = useState<Extension[]>([]);
  const [updates, setUpdates] = useState<Update[]>([]);
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [doctorData, setDoctorData] = useState<{ status: string; checks: DoctorCheck[] } | null>(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<{ text: string; type: 'success' | 'error' } | null>(null);

  useEffect(() => {
    fetchExtensions();
    fetchUpdates();
    fetchDoctor();
  }, []);

  const fetchExtensions = async () => {
    try {
      const res = await fetch('/api/extensions');
      const data = await res.json();
      setExtensions(data);
    } catch (e) {
      console.error("Failed to fetch extensions", e);
    }
  };

  const fetchUpdates = async () => {
    try {
      const res = await fetch('/api/updates');
      const data = await res.json();
      setUpdates(data);
    } catch (e) {
      console.error("Failed to fetch updates", e);
    }
  };

  const fetchDoctor = async () => {
    try {
      const res = await fetch('/api/doctor');
      const data = await res.json();
      setDoctorData(data);
    } catch (e) {
      console.error("Failed to fetch doctor data", e);
    }
  };

  const handleRefreshUpdates = async () => {
    setLoading(true);
    await fetch('/api/refresh-updates', { method: 'POST' });
    await fetchUpdates();
    setLoading(false);
    showToast('Updates refreshed');
  };

  const handleUpdateAll = async () => {
    setLoading(true);
    await fetch('/api/update-all', { method: 'POST' });
    await fetchExtensions();
    await fetchUpdates();
    setLoading(false);
    showToast('All extensions updated');
  };

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    const res = await fetch(`/api/search?q=${searchQuery}`);
    const data = await res.json();
    setSearchResults(data);
    setLoading(false);
  };

  const handleRemove = async (name: string) => {
    if (!confirm(`Are you sure you want to remove ${name}?`)) return;
    await fetch('/api/remove', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    fetchExtensions();
    showToast(`Extension ${name} removed`);
  };

  const showToast = (text: string, type: 'success' | 'error' = 'success') => {
    setMessage({ text, type });
    setTimeout(() => setMessage(null), 3000);
  };

  return (
    <div className="min-h-screen p-8 max-w-5xl mx-auto">
      {/* Header */}
      <header className="mb-12 border-b-2 border-ink pb-4 flex justify-between items-end">
        <div>
          <h1 className="text-4xl font-bold tracking-tighter uppercase flex items-center gap-3">
            <Terminal size={32} />
            Sysext Manager
          </h1>
          <p className="col-header mt-2">System Extension Creator & Manager v3.1-rc2</p>
        </div>
        <div className="text-right">
          <p className="text-xs font-mono uppercase opacity-50">Host: fedora-workstation</p>
          <p className="text-xs font-mono uppercase opacity-50">Status: {doctorData?.status === 'healthy' ? 'CONNECTED' : 'OFFLINE'}</p>
        </div>
      </header>

      {/* Tabs */}
      <nav className="flex gap-2 mb-8">
        {[
          { id: 'extensions', label: 'Extensions', icon: Package },
          { id: 'update', label: 'Update', icon: RefreshCw },
          { id: 'search', label: 'Search', icon: SearchIcon },
          { id: 'doctor', label: 'Doctor', icon: Stethoscope },
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id as Tab)}
            className={`btn-tech flex items-center gap-2 ${activeTab === tab.id ? 'tab-active' : 'tab-inactive opacity-60'}`}
          >
            <tab.icon size={14} />
            {tab.label}
          </button>
        ))}
      </nav>

      {/* Content */}
      <main className="border-t border-l border-ink bg-white/50 min-h-[400px]">
        <AnimatePresence mode="wait">
          <motion.div
            key={activeTab}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            transition={{ duration: 0.2 }}
          >
            {activeTab === 'extensions' && (
              <div>
                <div className="data-row bg-ink text-bg">
                  <span className="col-header text-bg">Extension Name</span>
                  <span className="col-header text-bg">Version</span>
                  <span className="col-header text-bg">Packages</span>
                  <span className="col-header text-bg">Action</span>
                </div>
                {extensions.map((ext) => (
                  <div key={ext.name} className="data-row group">
                    <span className="font-bold">{ext.name}</span>
                    <span className="data-value text-sm">{ext.version}</span>
                    <span className="text-xs opacity-60">{ext.packages}</span>
                    <button 
                      onClick={() => handleRemove(ext.name)}
                      className="text-red-600 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity"
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                ))}
              </div>
            )}

            {activeTab === 'update' && (
              <div>
                <div className="p-4 border-b border-ink flex justify-between items-center">
                  <p className="text-xs font-mono uppercase">
                    {updates.length} updates available
                  </p>
                  <div className="flex gap-2">
                    <button 
                      onClick={handleRefreshUpdates}
                      disabled={loading}
                      className="btn-tech flex items-center gap-2"
                    >
                      <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
                      Refresh
                    </button>
                    {updates.length > 0 && (
                      <button 
                        onClick={handleUpdateAll}
                        disabled={loading}
                        className="btn-tech flex items-center gap-2 bg-ink text-bg"
                      >
                        <Download size={14} />
                        Update All
                      </button>
                    )}
                  </div>
                </div>
                <div className="data-row bg-ink/5">
                  <span className="col-header">Package</span>
                  <span className="col-header">Current</span>
                  <span className="col-header">Latest</span>
                  <span className="col-header">Status</span>
                </div>
                {updates.length === 0 ? (
                  <div className="p-12 text-center opacity-30 italic">
                    All extensions are up to date.
                  </div>
                ) : (
                  updates.map((upd) => (
                    <div key={upd.name} className="data-row">
                      <span className="font-bold">{upd.name}</span>
                      <span className="data-value text-sm opacity-50">{upd.current}</span>
                      <span className="data-value text-sm text-green-700 font-bold">{upd.latest}</span>
                      <span className="text-[10px] uppercase tracking-widest text-green-700">Available</span>
                    </div>
                  ))
                )}
              </div>
            )}

            {activeTab === 'search' && (
              <div>
                <form onSubmit={handleSearch} className="p-4 border-b border-ink flex gap-2">
                  <input 
                    type="text" 
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Search Fedora repositories..."
                    className="flex-1 bg-transparent border border-ink p-2 text-sm focus:outline-none"
                  />
                  <button type="submit" className="btn-tech bg-ink text-bg">
                    Search
                  </button>
                </form>
                <div className="p-4">
                  {searchResults.length === 0 ? (
                    <div className="p-12 text-center opacity-30 italic">
                      Search for packages to install as extensions.
                    </div>
                  ) : (
                    <div className="grid gap-4">
                      {searchResults.map((pkg) => (
                        <div key={pkg.name} className="border border-ink p-4 flex justify-between items-start hover:bg-ink hover:text-bg transition-colors group">
                          <div>
                            <h3 className="font-bold uppercase tracking-tight">{pkg.name}</h3>
                            <p className="text-sm opacity-70 mt-1">{pkg.description}</p>
                          </div>
                          <button className="btn-tech group-hover:border-bg">
                            Install
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}

            {activeTab === 'doctor' && (
              <div className="p-6">
                <div className="flex items-center gap-4 mb-8">
                  <Activity className="text-ink" size={32} />
                  <div>
                    <h2 className="text-xl font-bold uppercase">System Diagnostics</h2>
                    <p className="text-xs opacity-50">Checking sysext-creator infrastructure health</p>
                  </div>
                </div>
                
                <div className="grid gap-4">
                  {doctorData?.checks.map((check) => (
                    <div key={check.name} className="border border-ink p-4 flex items-center gap-4">
                      {check.status === 'ok' ? (
                        <CheckCircle2 className="text-green-700" size={20} />
                      ) : (
                        <AlertCircle className="text-red-600" size={20} />
                      )}
                      <div className="flex-1">
                        <p className="text-xs font-mono uppercase opacity-50">{check.name}</p>
                        <p className="font-bold">{check.message}</p>
                      </div>
                      <div className={`text-[10px] font-bold uppercase px-2 py-1 ${check.status === 'ok' ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
                        {check.status}
                      </div>
                    </div>
                  ))}
                </div>

                <div className="mt-8 p-4 border border-dashed border-ink opacity-50">
                  <p className="text-[10px] font-mono uppercase mb-2">System Logs</p>
                  <pre className="text-[10px] leading-tight">
                    [2026-03-22 09:10:18] INFO: systemd-sysext refresh successful{"\n"}
                    [2026-03-22 09:10:21] INFO: systemd-tmpfiles --create executed{"\n"}
                    [2026-03-22 09:10:21] INFO: /etc/mc/sfs.ini symlink verified{"\n"}
                    [2026-03-22 09:11:05] INFO: Varlink connection stable
                  </pre>
                </div>
              </div>
            )}
          </motion.div>
        </AnimatePresence>
      </main>

      {/* Toast */}
      <AnimatePresence>
        {message && (
          <motion.div 
            initial={{ opacity: 0, y: 50 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 50 }}
            className="fixed bottom-8 right-8 bg-ink text-bg px-6 py-3 shadow-2xl flex items-center gap-3 border border-white/20"
          >
            <Activity size={16} className="animate-pulse" />
            <span className="text-sm font-bold uppercase tracking-widest">{message.text}</span>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Footer */}
      <footer className="mt-12 pt-4 border-t border-ink flex justify-between items-center opacity-30">
        <p className="text-[10px] font-mono uppercase">© 2026 Sysext Project - Fedora Atomic Desktop</p>
        <div className="flex gap-4">
          <p className="text-[10px] font-mono uppercase">Kernel: 6.12.0-fc43</p>
          <p className="text-[10px] font-mono uppercase">Architecture: x86_64</p>
        </div>
      </footer>
    </div>
  );
}
