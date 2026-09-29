// Política de privacidad (Ley 25.326 de Protección de Datos Personales). Página pública: se puede leer sin ingresar.
// Texto base: conviene que lo revise un abogado antes de publicar la plataforma para terceros.
import Link from "next/link";

export const metadata = { title: "Política de privacidad · Retail IA" };

const VERSION = "2026-09";

export default function Privacidad() {
  return (
    <main className="mx-auto grid max-w-3xl gap-4 px-4 py-10 text-sm leading-relaxed">
      <h1 className="text-2xl font-semibold">Política de privacidad</h1>
      <p className="text-suave">Versión {VERSION}. Rige para Retail IA y el Panel ERP.</p>

      <h2 className="text-lg font-semibold">1. Quién trata los datos</h2>
      <p>La plataforma trata los datos que cada empresa carga o conecta (su sistema de caja, sus tiendas online, sus archivos) solo para
        darle a esa empresa sus análisis y recomendaciones. Cada empresa es responsable de los datos de sus clientes; la plataforma actúa
        por cuenta de ella (encargada del tratamiento, Ley 25.326, art. 25).</p>

      <h2 className="text-lg font-semibold">2. Qué datos se usan</h2>
      <ul className="list-disc pl-5">
        <li>De los usuarios: nombre, email, rol, registro de ingresos y acciones (auditoría).</li>
        <li>De la empresa: ventas, stock, productos, costos, proveedores, compras, precios y canales.</li>
        <li>De clientes finales, solo si la caja los identifica y el cliente dio su consentimiento: un identificador, nombre y sus compras.</li>
      </ul>

      <h2 className="text-lg font-semibold">3. Para qué</h2>
      <p>Para calcular reposición, precios, alertas y reportes de la propia empresa. No se venden datos. Los datos de una empresa nunca se
        muestran a otra. El único uso fuera de la empresa es el panel para distribuidores y marcas, y solo si la empresa lo autoriza
        expresamente: son datos agregados y anónimos de al menos 5 comercios, sin nombres ni datos de clientes.</p>

      <h2 className="text-lg font-semibold">4. Cómo se protegen</h2>
      <p>Conexión cifrada (HTTPS), claves guardadas con hash, credenciales de las integraciones cifradas, segundo factor opcional, aislamiento
        por empresa en la base de datos, registro de auditoría y copias de seguridad diarias.</p>

      <h2 className="text-lg font-semibold">5. Tus derechos</h2>
      <ul className="list-disc pl-5">
        <li><strong>Acceso:</strong> el dueño descarga todos los datos de su empresa en Configuración → Tus datos.</li>
        <li><strong>Rectificación:</strong> los datos se corrigen desde las pantallas o desde el sistema de origen.</li>
        <li><strong>Supresión:</strong> el dueño puede pedir la baja de la empresa (se borra todo después de 30 días, plazo para
          arrepentirse) y suprimir los datos de un cliente final en cualquier momento.</li>
      </ul>
      <p>La Agencia de Acceso a la Información Pública, órgano de control de la Ley 25.326, atiende las denuncias y reclamos por
        incumplimiento de las normas sobre protección de datos personales.</p>

      <h2 className="text-lg font-semibold">6. Conservación</h2>
      <p>Los datos se conservan mientras la empresa use la plataforma. Después de una baja se borran; el registro de auditoría se conserva sin
        datos de la empresa para poder responder a controles. Las copias de seguridad se guardan 7 días.</p>

      <p className="pt-4"><Link className="text-acento underline" href="/">Volver</Link></p>
    </main>
  );
}
