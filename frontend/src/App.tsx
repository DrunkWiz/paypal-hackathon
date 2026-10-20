import { Routes, Route } from "react-router-dom";
import MerchantPage from "./pages/MerchantPage";
import ResolvePage from "./pages/ResolvePage";

export default function App() {
  return (
    <>
      <header style={{ padding: "1rem", borderBottom: "1px solid var(--border)" }}>
        Settle
      </header>
      <Routes>
        <Route path="/" element={<MerchantPage />} />
        <Route path="/merchant" element={<MerchantPage />} />
        <Route path="/resolve/:token" element={<ResolvePage />} />
      </Routes>
    </>
  );
}