import Link from "next/link";

export default function NoEncontrada() {
  return (
    <main className="grid min-h-dvh place-items-center px-4 text-center">
      <div>
        <h1 className="text-xl font-semibold">No encontramos esa página</h1>
        <Link href="/" className="mt-2 inline-block text-acento underline">Volver al inicio</Link>
      </div>
    </main>
  );
}
