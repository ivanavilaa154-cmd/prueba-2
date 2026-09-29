// Pantalla de un módulo que el plan de la empresa no incluye (13.6).
import Link from "next/link";
import { Vacio } from "./ui";

export function NoIncluido() {
  return (
    <Vacio titulo="🔒 No está incluido en tu plan">
      Esta parte es de un plan superior. <Link className="text-acento underline" href="/configuracion/#plan">Ver planes</Link>
    </Vacio>
  );
}
