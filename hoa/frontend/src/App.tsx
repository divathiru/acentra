import { Routes, Route, Navigate } from 'react-router-dom';
import LoginPage from './pages/LoginPage';
import ChatPage from './pages/ChatPage';
import AdminPage from './pages/AdminPage';
import RequireAuth from './components/RequireAuth';

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />

      {/* Employee + above: chat */}
      <Route
        path="/chat"
        element={
          <RequireAuth perm="chat:use">
            <ChatPage />
          </RequireAuth>
        }
      />

      {/* Agent + admin only: admin area */}
      <Route
        path="/admin/*"
        element={
          <RequireAuth adminOnly>
            <AdminPage />
          </RequireAuth>
        }
      />

      {/* Default → login */}
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  );
}
