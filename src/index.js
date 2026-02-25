/**
 * src/index.js
 * Express application entry point for the Nexus Graph API.
 */

require("dotenv").config();
const express = require("express");
const app = express();

// ---- Middleware ----
app.use(express.json());

// Request logger (simple)
app.use((req, _res, next) => {
    console.log(`${new Date().toISOString()} ${req.method} ${req.url}`);
    next();
});

// ---- Routes ----
const companiesRouter = require("./routes/companies");
app.use("/companies", companiesRouter);

// Health check
app.get("/health", (_req, res) => {
    res.json({ status: "ok", timestamp: new Date().toISOString() });
});

// 404 handler
app.use((_req, res) => {
    res.status(404).json({ error: "Route not found" });
});

// Global error handler
app.use((err, _req, res, _next) => {
    console.error("Unhandled error:", err);
    res.status(500).json({ error: "Internal server error" });
});

// ---- Start ----
const PORT = process.env.PORT || 3000;

// Only start the server when this file is run directly (not when required by tests)
if (require.main === module) {
    app.listen(PORT, () => {
        console.log(`🚀 Nexus API listening on http://localhost:${PORT}`);
    });
}

module.exports = app;
