// The rail's category glyphs and subtitles, from Kiosk Satellite 2026.9.87
// (app/remote-ui/index.html, the nav#tabs buttons), keyed by the settings
// category they open, so a Panel Fleet page wears the panel's own icon.

export const CATEGORY_NAV = {
  "Home Assistant": { sub: "Connection, dashboard, kiosk mode",
    svg: "<svg viewBox=\"1.31 0.97 21.4 21.4\" fill=\"currentColor\"><path d=\"M21.8,13H20V21H13V17.67L15.79,14.88L16.5,15C17.66,15 18.6,14.06 18.6,12.9C18.6,11.74 17.66,10.8 16.5,10.8A2.1,2.1 0 0,0 14.4,12.9L14.5,13.61L13,15.13V9.65C13.66,9.29 14.1,8.6 14.1,7.8A2.1,2.1 0 0,0 12,5.7A2.1,2.1 0 0,0 9.9,7.8C9.9,8.6 10.34,9.29 11,9.65V15.13L9.5,13.61L9.6,12.9A2.1,2.1 0 0,0 7.5,10.8A2.1,2.1 0 0,0 5.4,12.9A2.1,2.1 0 0,0 7.5,15L8.21,14.88L11,17.67V21H4V13H2.25C1.83,13 1.42,13 1.42,12.79C1.43,12.57 1.85,12.15 2.28,11.72L11,3C11.33,2.67 11.67,2.33 12,2.33C12.33,2.33 12.67,2.67 13,3L17,7V6H19V9L21.78,11.78C22.18,12.18 22.59,12.59 22.6,12.8C22.6,13 22.2,13 21.8,13M7.5,12A0.9,0.9 0 0,1 8.4,12.9A0.9,0.9 0 0,1 7.5,13.8A0.9,0.9 0 0,1 6.6,12.9A0.9,0.9 0 0,1 7.5,12M16.5,12C17,12 17.4,12.4 17.4,12.9C17.4,13.4 17,13.8 16.5,13.8A0.9,0.9 0 0,1 15.6,12.9A0.9,0.9 0 0,1 16.5,12M12,6.9C12.5,6.9 12.9,7.3 12.9,7.8C12.9,8.3 12.5,8.7 12,8.7C11.5,8.7 11.1,8.3 11.1,7.8C11.1,7.3 11.5,6.9 12,6.9Z\"/></svg>" },
  "Voice Satellite": { sub: "Wake word, background listening",
    svg: "<svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\"><path d=\"M4 10v4M8 7v10M12 4v16M16 7v10M20 10v4\"/></svg>" },
  "Screen & Audio": { sub: "Brightness, volume, microphone",
    svg: "<svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\"><circle cx=\"12\" cy=\"12\" r=\"4\"/><path d=\"M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4m11.4-11.4 1.4-1.4\"/></svg>" },
  "Browser": { sub: "Cache, SSL, Zoom level",
    svg: "<svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\"><circle cx=\"12\" cy=\"12\" r=\"9\"/><path d=\"M3 12h18M12 3a13.5 13.5 0 0 1 0 18M12 3a13.5 13.5 0 0 0 0 18\"/></svg>" },
  "Screensaver": { sub: "Idle timeout, modes, motion wake",
    svg: "<svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linejoin=\"round\"><path d=\"M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z\"/></svg>" },
  "Camera": { sub: "Device camera, motion, streaming",
    svg: "<svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><path d=\"M4 8a2 2 0 0 1 2-2h1.5l1.2-1.6a2 2 0 0 1 1.6-.8h3.4a2 2 0 0 1 1.6.8L16.5 6H18a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z\"/><circle cx=\"12\" cy=\"12.5\" r=\"3.5\"/></svg>" },
  "Sendspin": { sub: "Music Assistant, Sendspin, Sonos",
    svg: "<svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><circle cx=\"12\" cy=\"12\" r=\"10\"/><path d=\"m9.75 7.5 7 4.5-7 4.5z\"/></svg>" },
  "Cameras": { sub: "Go2RTC and Home Assistant cameras",
    svg: "<svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><rect x=\"3\" y=\"5\" width=\"14\" height=\"14\" rx=\"2.5\"/><path d=\"m17 10 4-2v8l-4-2z\"/></svg>" },
  "DLNA": { sub: "Play images, videos and audio remotely",
    svg: "<svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><path d=\"M3 19h.01M3 15a4 4 0 0 1 4 4M3 11a8 8 0 0 1 8 8\"/><path d=\"M8 5h11a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2h-4\"/></svg>" },
  "ESPHome": { sub: "Native entities and Bluetooth proxy",
    svg: "<svg viewBox=\"-14 -14 284 284\" fill=\"currentColor\"><path fill-rule=\"evenodd\" d=\"M118 6 Q128 -2 138 6 L246 90 Q254 96 254 106 L254 234 Q254 254 234 254 L22 254 Q2 254 2 234 L2 106 Q2 96 10 90 Z M80 88 h12 v164 h-12 z M92 88 h88 v12 h-88 z M168 100 h12 v12 h-12 z M108 112 h72 v12 h-72 z M108 124 h12 v13 h-12 z M108 137 h72 v12 h-72 z M168 149 h12 v15 h-12 z M108 164 h72 v12 h-72 z M108 176 h12 v14 h-12 z M108 190 h72 v12 h-72 z M168 202 h12 v12 h-12 z M108 214 h72 v12 h-72 z\"/></svg>" },
  "Kiosk": { sub: "Exit gesture, PIN, hardware buttons",
    svg: "<svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><rect x=\"5\" y=\"11\" width=\"14\" height=\"10\" rx=\"2.5\"/><path d=\"M8 11V7a4 4 0 0 1 8 0v4\"/></svg>" },
  "Lockdown": { sub: "Disable screen interactions",
    svg: "<svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><path d=\"M12 3l7 3v5c0 4.6-3 8.4-7 9.5C8 19.4 5 15.6 5 11V6l7-3z\"/><rect x=\"9.5\" y=\"10\" width=\"5\" height=\"4.5\" rx=\"1\"/><path d=\"M10.7 10V8.8a1.3 1.3 0 0 1 2.6 0V10\"/></svg>" },
  "Home": { sub: "Replace the device home screen",
    svg: "<svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><path d=\"M3 10.5 12 3l9 7.5\"/><path d=\"M5 9.5V19a2 2 0 0 0 2 2h3.5v-5.5h3V21H17a2 2 0 0 0 2-2V9.5\"/></svg>" },
  "Launcher": { sub: "Open other apps from the kiosk",
    svg: "<svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><rect x=\"4\" y=\"4\" width=\"6\" height=\"6\" rx=\"1.5\"/><rect x=\"14\" y=\"4\" width=\"6\" height=\"6\" rx=\"1.5\"/><rect x=\"4\" y=\"14\" width=\"6\" height=\"6\" rx=\"1.5\"/><rect x=\"14\" y=\"14\" width=\"6\" height=\"6\" rx=\"1.5\"/></svg>" },
  "Gestures": { sub: "Touch, palm and clap gestures",
    svg: "<svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><path d=\"M4 9c1-2 2.6-3.6 3.7-3 1.3.7-1.3 3.4-2.1 5.3-.9 2.2-.4 4.7 1.9 4.7 3.2 0 4.5-6.5 8-6.5 2.4 0 3 2 3 3.5 0 2.6-1.7 5-4 5-1.4 0-2.3-1-2.3-2.1 0-1.5 1.5-2.9 3.6-2.9H21\"/></svg>" },
  "Intercom": { sub: "Talk between kiosks",
    svg: "<svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><rect x=\"3\" y=\"3\" width=\"11\" height=\"18\" rx=\"2.5\"/><circle cx=\"8.5\" cy=\"9\" r=\"2.2\"/><path d=\"M6.5 15.5h4\"/><path d=\"M17.5 8.5a5 5 0 0 1 0 7M20 6a8.5 8.5 0 0 1 0 12\"/></svg>" },
  "Device": { sub: "Name, app theme, remote access",
    svg: "<svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\"><rect x=\"5\" y=\"3\" width=\"14\" height=\"18\" rx=\"2.5\"/><path d=\"M10.5 17.5h3\"/></svg>" },
};

// Panel Fleet's own pages, in the same stroke style.
export const PAGE_NAV = {
  panels: "<svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linejoin=\"round\"><rect x=\"3\" y=\"3\" width=\"7\" height=\"7\" rx=\"1.5\"/><rect x=\"14\" y=\"3\" width=\"7\" height=\"7\" rx=\"1.5\"/><rect x=\"3\" y=\"14\" width=\"7\" height=\"7\" rx=\"1.5\"/><rect x=\"14\" y=\"14\" width=\"7\" height=\"7\" rx=\"1.5\"/></svg>",
  fleet: "<svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><circle cx=\"12\" cy=\"12\" r=\"3\"/><circle cx=\"5\" cy=\"6\" r=\"2\"/><circle cx=\"19\" cy=\"6\" r=\"2\"/><circle cx=\"12\" cy=\"20\" r=\"2\"/><path d=\"M9.8 10.4 6.4 7.6M14.2 10.4l3.4-2.8M12 15v3\"/></svg>",
  updates: "<svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><path d=\"M12 4v11M7.5 10.5 12 15l4.5-4.5\"/><path d=\"M5 19h14\"/></svg>",
  wake: "<svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><rect x=\"9\" y=\"3\" width=\"6\" height=\"11\" rx=\"3\"/><path d=\"M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21\"/></svg>",
  profiles: "<svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><rect x=\"4\" y=\"3\" width=\"16\" height=\"18\" rx=\"2.5\"/><path d=\"M8 8h8M8 12h8M8 16h5\"/></svg>",
};
