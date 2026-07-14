import { initializeApp } from "firebase/app";
import { getAuth, signInWithCustomToken } from "firebase/auth";
import { getFirestore } from "firebase/firestore";

// Config pública de la Web App (Firebase la diseña para vivir en el cliente;
// la seguridad la dan las reglas de Firestore, no ocultar esto).
const firebaseConfig = {
  apiKey: "AIzaSyBJPV3IDVKzcBJND-_-1BBs7YY1dphBZuQ",
  authDomain: "u2nyawjl-88b6d.firebaseapp.com",
  projectId: "u2nyawjl-88b6d",
  appId: "1:768531938155:web:d945435b35d6117453ea2e",
  messagingSenderId: "768531938155",
};

const app = initializeApp(firebaseConfig);
export const auth = getAuth(app);
export const db = getFirestore(app);

const API_BASE = "https://u2scribe-gateway.vercel.app";

// Login: el token del dashboard se canjea en /auth por un custom token, y con él
// se inicia sesión en Firebase. A partir de ahí las lecturas van directas a Firestore.
export async function signInWithDashboardToken(token: string): Promise<void> {
  const resp = await fetch(`${API_BASE}/auth`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!resp.ok) throw new Error(String(resp.status));
  const { firebase_token } = await resp.json();
  await signInWithCustomToken(auth, firebase_token);
}
