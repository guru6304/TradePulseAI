import React, { useState } from 'react';
import { Header } from './Header';
import { Sidebar } from './Sidebar';
import { MobileNav } from './MobileNav';
import { XRayDrawer } from '../../views/XRayDrawer';

interface ShellProps {
  children: React.ReactNode;
}

export const Shell: React.FC<ShellProps> = ({ children }) => {
  const [isMobileDrawerOpen, setIsMobileDrawerOpen] = useState(false);

  return (
    <div className="min-h-screen bg-surface text-on-surface flex flex-col antialiased">
      {/* Desktop Persistent Sidebar (hidden on mobile) */}
      <Sidebar />

      {/* Header (responsive left offset for desktop sidebar) */}
      <Header onToggleMobileNav={() => setIsMobileDrawerOpen(true)} />

      {/* Mobile Bottom Navigation + Slide Drawer */}
      <MobileNav
        isDrawerOpen={isMobileDrawerOpen}
        onCloseDrawer={() => setIsMobileDrawerOpen(false)}
      />

      {/* Main Content Workspace */}
      <main
        id="main-content"
        className="flex-1 md:pl-56 pt-[4.25rem] pb-16 md:pb-space-lg min-h-screen bg-surface flex flex-col"
        tabIndex={-1}
      >
        {children}
      </main>

      {/* Opportunity X-Ray Detail Modal Dialog */}
      <XRayDrawer />
    </div>
  );
};

