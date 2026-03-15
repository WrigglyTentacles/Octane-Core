import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import './index.css';
import { AuthProvider } from './AuthContext';
import { GuildProvider } from './GuildContext';
import App from './App';
import LoginPage from './LoginPage';
import SettingsPage from './SettingsPage';
import WinnersPage from './WinnersPage';
import RegisterPage from './RegisterPage';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <GuildProvider>
          <Routes>
            <Route path="/" element={<App />} />
            <Route path="/current/*" element={<App isCurrentPage />} />
            <Route path="/winners" element={<WinnersPage />} />
            <Route path="/participants" element={<App />} />
            <Route path="/standby" element={<App />} />
            <Route path="/teams" element={<App />} />
            <Route path="/bracket" element={<App />} />
            <Route path="/login" element={<LoginPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/s/:guildId/settings" element={<SettingsPage />} />
            <Route path="/s/:guildId/register" element={<RegisterPage />} />
            <Route path="/s/:guildId" element={<App />} />
            <Route path="/s/:guildId/teams" element={<App />} />
            <Route path="/s/:guildId/bracket" element={<App />} />
            <Route path="/s/:guildId/current/*" element={<App isCurrentPage />} />
            <Route path="/s/:guildId/winners" element={<WinnersPage />} />
          </Routes>
        </GuildProvider>
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>
);
