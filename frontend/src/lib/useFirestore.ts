import { useEffect, useState } from "react";
import {
  collection, doc, limit, onSnapshot, orderBy, query,
} from "firebase/firestore";
import { db } from "./firebase";

// Suscripción en vivo a un documento. Se pinta al instante desde caché local y
// se actualiza solo cuando el heartbeat escribe. Sin polling, sin cold start.
export function useDoc<T = any>(path: string): T | null {
  const [data, setData] = useState<T | null>(() => readCache(path));
  useEffect(() => {
    const [col, id] = path.split("/");
    return onSnapshot(doc(db, col, id), (snap) => {
      const v = (snap.data() as T) ?? null;
      setData(v);
      writeCache(path, v);
    });
  }, [path]);
  return data;
}

// Suscripción en vivo a una colección, ordenada por `field` descendente.
export function useCollection<T = any>(name: string, field: string, max = 100): T[] {
  const [rows, setRows] = useState<T[]>(() => readCache("col:" + name) || []);
  useEffect(() => {
    const q = query(collection(db, name), orderBy(field, "desc"), limit(max));
    return onSnapshot(q, (snap) => {
      const v = snap.docs.map((d) => ({ id: d.id, ...d.data() }) as T);
      setRows(v);
      writeCache("col:" + name, v);
    });
  }, [name, field, max]);
  return rows;
}

function readCache(key: string): any {
  try {
    const raw = localStorage.getItem("fs:" + key);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}
function writeCache(key: string, v: any) {
  try {
    localStorage.setItem("fs:" + key, JSON.stringify(v));
  } catch { /* cuota llena */ }
}
