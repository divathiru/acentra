/**
 * Route guard HOC.
 * Usage:
 *   <RequireAuth perm="chat:use"><ChatPage /></RequireAuth>
 *   <RequireAuth perm="analytics:read"><AnalyticsPage /></RequireAuth>
 */

import { type ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuthStore, hasPerm, canAccessAdmin } from '../store/authStore';

interface RequireAuthProps {
  children: ReactNode;
  /** If provided, user must have this permission. If absent, just needs to be logged in. */
  perm?: string;
  /** If true, requires agent or admin (for /admin). */
  adminOnly?: boolean;
}

export default function RequireAuth({ children, perm, adminOnly }: RequireAuthProps) {
  const { claims, access_token } = useAuthStore();
  const location = useLocation();

  // Not logged in at all
  if (!access_token || !claims) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  // Admin area gate
  if (adminOnly && !canAccessAdmin(claims)) {
    return <Navigate to="/chat" replace />;
  }

  // Specific permission gate
  if (perm && !hasPerm(claims, perm)) {
    return <Navigate to="/chat" replace />;
  }

  return <>{children}</>;
}
