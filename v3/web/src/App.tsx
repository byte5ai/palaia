import { RouterProvider } from "react-router-dom";

import { ToastProvider } from "./components";
import { ThemeProvider } from "./lib/theme";
import { router } from "./routes";

function App() {
  return (
    <ThemeProvider>
      <ToastProvider>
        <RouterProvider router={router} />
      </ToastProvider>
    </ThemeProvider>
  );
}

export default App;
