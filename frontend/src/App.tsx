import { useEffect, useState } from "react";
import { Link, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { api } from "./api";
import LandingPage from "./pages/LandingPage";
import MerchantPage from "./pages/MerchantPage";
import ResolvePage from "./pages/ResolvePage";

export type ThemeMode = "system" | "light" | "dark";

export default function App() {
  const location = useLocation();
  const navigate = useNavigate();
  const [theme, setTheme] = useState<ThemeMode>(
    () => (localStorage.getItem("settle.theme") as ThemeMode) || "system",
  );
  const [launchingOrder, setLaunchingOrder] = useState<string | null>(null);

  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") {
      delete root.dataset.theme;
    } else {
      root.dataset.theme = theme;
    }
    localStorage.setItem("settle.theme", theme);
  }, [theme]);

  const cycleTheme = () => {
    setTheme((prev) =>
      prev === "system" ? "light" : prev === "light" ? "dark" : "system",
    );
  };

  const openSampleCustomerFlow = async (
    orderId: string,
    overCapDemo = false,
  ) => {
    setLaunchingOrder(orderId);
    try {
      const merchantId =
        localStorage.getItem("settle.merchantId") || "m_kopiclay";
      const link = await api.createResolveLink(merchantId, orderId);
      const query = overCapDemo
        ? `?overcap=1&t=${Date.now()}`
        : `?t=${Date.now()}`;
      navigate(`/resolve/${encodeURIComponent(link.token)}${query}`);
    } catch {
      navigate("/merchant");
    } finally {
      setLaunchingOrder(null);
    }
  };

  const isResolveView = location.pathname.startsWith("/resolve");

  const isOverCapResolve = (() => {
    if (!isResolveView) return false;
    if (location.search.includes("overcap=1")) return true;
    const rawToken = decodeURIComponent(
      location.pathname.replace(/^\/resolve\//, ""),
    );
    const payloadPart = rawToken.split(".")[0];
    if (!payloadPart) return false;
    try {
      const base64 = payloadPart.replace(/-/g, "+").replace(/_/g, "/");
      const padded = base64 + "=".repeat((4 - (base64.length % 4)) % 4);
      const parsed = JSON.parse(window.atob(padded)) as { order_id?: string };
      return (
        parsed.order_id === "ORDER-003" ||
        parsed.order_id === "ORDER-002" ||
        parsed.order_id === "ORDER-008" ||
        parsed.order_id === "ORDER-013" ||
        parsed.order_id === "ORDER-023"
      );
    } catch {
      return false;
    }
  })();

  const themeLabel =
    theme === "system" ? "Auto" : theme === "light" ? "Light" : "Dark";

  return (
    <>
      {isResolveView ? (
        <header className="portal-topbar">
          <div className="row" style={{ gap: 10 }}>
            <Link to="/merchant" className="ops-brand-link">
              <span className="ops-brand-mark" aria-hidden="true">
                S
              </span>
              <span>Settle</span>
            </Link>
            <span className="ops-breadcrumb-sep" aria-hidden="true">
              /
            </span>
            <span className="badge no-dot">Buyer Resolution Portal</span>
          </div>

          <nav className="row" style={{ gap: 8 }} aria-label="Portal navigation">
            <div className="ops-segmented">
              <button
                type="button"
                className={
                  !isOverCapResolve ? "ops-segment-btn active" : "ops-segment-btn"
                }
                disabled={launchingOrder !== null}
                onClick={() => void openSampleCustomerFlow("ORDER-001", false)}
              >
                {launchingOrder === "ORDER-001"
                  ? "Loading…"
                  : "Standard Order ($24)"}
              </button>
              <button
                type="button"
                className={
                  isOverCapResolve ? "ops-segment-btn active" : "ops-segment-btn"
                }
                disabled={launchingOrder !== null}
                onClick={() => void openSampleCustomerFlow("ORDER-003", true)}
              >
                {launchingOrder === "ORDER-003"
                  ? "Loading…"
                  : "Over-Cap Order ($89)"}
              </button>
            </div>

            <Link to="/merchant" className="btn sm secondary">
              Merchant Console
            </Link>

            <button
              type="button"
              className="btn sm ghost"
              onClick={cycleTheme}
              aria-label={`Color theme: ${theme}. Activate to switch theme.`}
            >
              <span>Theme: {themeLabel}</span>
            </button>
          </nav>
        </header>
      ) : null}

      <Routes>
        <Route
          path="/"
          element={
            <LandingPage
              theme={theme}
              onCycleTheme={cycleTheme}
              onOpenCustomerFlow={openSampleCustomerFlow}
              launchingOrder={launchingOrder}
            />
          }
        />
        <Route
          path="/merchant"
          element={
            <MerchantPage
              theme={theme}
              onCycleTheme={cycleTheme}
              onOpenCustomerFlow={openSampleCustomerFlow}
              launchingOrder={launchingOrder}
            />
          }
        />
        <Route path="/resolve/:token" element={<ResolvePage />} />
      </Routes>
    </>
  );
}
