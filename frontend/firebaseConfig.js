import { initializeApp } from "firebase/app";
import { getAuth } from "firebase/auth";

// Your web app's Firebase configuration
const firebaseConfig = {
  apiKey: "AIzaSyBPv7h39z020nldikPiXvYerIg2za6u4DI",
  authDomain: "spillthereel-caa31.firebaseapp.com",
  projectId: "spillthereel-caa31",
  storageBucket: "spillthereel-caa31.firebasestorage.app",
  messagingSenderId: "829400295191",
  appId: "1:829400295191:web:35df24b5311d65445f7952",
  measurementId: "G-M8T7H7LVVF"
};

// Initialize Firebase
const app = initializeApp(firebaseConfig);
export const auth = getAuth(app);
export default app;
