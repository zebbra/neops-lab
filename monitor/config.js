// Runtime config for the monitor app, bind-mounted over
// rest/monitor-app/static/config.js in the workflow-engine-client service.
// src/app.html loads it as `%sveltekit.assets%/config.js`, and svelte.config.js
// leaves `static/` as the assets directory under `npm run dev`.
//
// webclientOrigin: the exact origin of the neops web client that relays access
// tokens to this app over postMessage. apiBaseUrl is omitted; the monitor's
// compile-time default is already http://localhost:3030.
window.__NEOPS_CONFIG__ = { webclientOrigin: 'http://localhost:8080' }
