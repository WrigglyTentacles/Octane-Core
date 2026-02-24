import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import './index.css';
import { AuthProvider } from './AuthContext';
import App from './App';
import LoginPage from './LoginPage';
import SettingsPage from './SettingsPage';
import WinnersPage from './WinnersPage';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthProvider>
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
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>
);
