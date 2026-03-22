module.exports = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#0f172a",
        mist: "#eef2ff",
        shell: "#f8fafc",
        accent: "#0f766e",
        ember: "#c2410c",
      },
      boxShadow: {
        panel: "0 18px 40px rgba(15, 23, 42, 0.08)",
      },
    },
  },
  plugins: [],
};

