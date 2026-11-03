import React from 'react';
import { TerminalProvider, useTerminal } from './context/TerminalContext';
import { Shell } from './components/layout/Shell';
import { PulseView } from './views/PulseView';
import { OpportunitiesView } from './views/OpportunitiesView';
import { OptionsView } from './views/OptionsView';
import { StrategiesView } from './views/StrategiesView';
import { PaperView } from './views/PaperView';
import { HealthView } from './views/HealthView';
import { AdminResearchView } from './views/AdminResearchView';

const RouteRenderer: React.FC = () => {
  const { route } = useTerminal();

  switch (route) {
    case 'pulse':
      return <PulseView />;
    case 'opportunities':
      return <OpportunitiesView />;
    case 'options':
      return <OptionsView />;
    case 'strategies':
      return <StrategiesView />;
    case 'paper':
      return <PaperView />;
    case 'health':
      return <HealthView />;
    case 'admin-research':
      return <AdminResearchView />;
    default:
      return <PulseView />;
  }
};

export const App: React.FC = () => {
  return (
    <TerminalProvider>
      <Shell>
        <RouteRenderer />
      </Shell>
    </TerminalProvider>
  );
};
