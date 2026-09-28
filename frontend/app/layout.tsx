import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Retail IA",
  description: "Inteligencia retail para comercios: qué comprar, qué transferir, qué remarcar y dónde está parada la plata.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

// Aplica el tema antes de pintar, para que no parpadee: el elegido por la persona o el del sistema.
const temaInicial = `try{var t=localStorage.getItem("retail_tema");if(t==="oscuro"||(!t&&matchMedia("(prefers-color-scheme: dark)").matches))document.documentElement.classList.add("dark")}catch(e){}`;

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="es-AR" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: temaInicial }} />
      </head>
      <body className="min-h-dvh">{children}</body>
    </html>
  );
}
