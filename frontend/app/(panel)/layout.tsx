import { Marco } from "@/components/Marco";
import { ProveedorSesion } from "@/components/Sesion";

export default function LayoutPanel({ children }: { children: React.ReactNode }) {
  return (
    <ProveedorSesion>
      <Marco>{children}</Marco>
    </ProveedorSesion>
  );
}
