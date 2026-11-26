import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  // 브라우저는 같은 출처의 API만 사용한다. Backend 설정 파일은 읽지 않는다.
  envDir: false,
  plugins: [react()],
  server: { proxy: { "/api": process.env.API_PROXY_TARGET || "http://127.0.0.1:8000" } },
});
