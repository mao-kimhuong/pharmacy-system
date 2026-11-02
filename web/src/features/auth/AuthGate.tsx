import type { ReactNode } from 'react';
import { useAuth } from '@/app/auth';
import { Splash } from '@/app/App';
import { AuthLayout } from './AuthLayout';
import { ForcedTwoFactorPage } from './ForcedTwoFactorPage';
import { LoginPage } from './LoginPage';
import { BackupCodes } from './TwoFactorSetup';
import { TwoFactorPage } from './TwoFactorPage';

export function AuthGate({ children }: { children: ReactNode }) {
  const { status, backupCodes, acknowledgeBackupCodes } = useAuth();
  if (status === 'booting') return <Splash />;
  if (status === 'anonymous') return <LoginPage />;
  if (status === 'mfa') return <TwoFactorPage />;
  if (status === 'setup') return <ForcedTwoFactorPage />;
  if (backupCodes) return <AuthLayout><BackupCodes codes={backupCodes} onDone={acknowledgeBackupCodes} /></AuthLayout>;
  return <>{children}</>;
}
