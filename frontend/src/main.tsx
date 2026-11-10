import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { ApiError } from "./lib/api";
import { ThemeProvider } from "./lib/theme";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60_000,
      refetchOnWindowFocus: false,
      // Retry only transient failures; auth/permission/quota/config errors won't fix themselves.
      retry: (count, err) => count < 2 && err instanceof ApiError && (err.status === 0 || (err.status >= 500 && err.status !== 503)),
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <App />
      </ThemeProvider>
    </QueryClientProvider>
  </StrictMode>,
);
