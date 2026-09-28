// Copia la exportación (out/) a backend/app/web/retail, que es lo que sirve la plataforma.
import { cpSync, rmSync, existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const aqui = dirname(fileURLToPath(import.meta.url));
const origen = resolve(aqui, "../out");
const destino = resolve(aqui, "../../backend/app/web/retail");
if (!existsSync(origen)) throw new Error("No existe out/: corré primero next build");
rmSync(destino, { recursive: true, force: true });
cpSync(origen, destino, { recursive: true });
console.log(`Pantallas de Retail copiadas a ${destino}`);
