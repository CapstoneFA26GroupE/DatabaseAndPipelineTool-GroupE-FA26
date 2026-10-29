import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import "./App.css";

import AppLayout from "./layouts/AppLayout";
import RouteDashboard from "./pages/RouteDashboard";
import RouteDetail from "./pages/RouteDetail";
import SegmentViewer from "./pages/SegmentViewer";
import JobDefinitions from "./pages/JobDefinitions";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Prevent redundant window-focus refetches on top of scheduled polls
      staleTime: 2000,
    },
  },
})

export default function App() {
  return (
    <BrowserRouter>
    <QueryClientProvider client={queryClient}>
      <Routes>
        {/* Redirect / → /routes */}
        <Route path="/" element={<Navigate to="/routes" replace />} />

        {/* All pages share the AppLayout (topbar + content wrapper) */}
        <Route element={<AppLayout />}>
          <Route path="/routes" element={<RouteDashboard />} />
          <Route path="/routes/:routeId" element={<RouteDetail />} />
          <Route path="/routes/:routeId/segments/:segmentId" element={<SegmentViewer />} />
          <Route path="/job-definitions" element={<JobDefinitions />} />
        </Route>
      </Routes>
      </QueryClientProvider>
    </BrowserRouter>
  );
}
