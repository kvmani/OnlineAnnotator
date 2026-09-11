/**
 * OnlineAnnotator Real-Time WebSocket Collaboration Listener
 */
const WS = {
  socket: null,
  pingInterval: null,

  init() {
    this.connect();
  },

  connect() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/api/v1/ws/collaborate`;

    try {
      this.socket = new WebSocket(wsUrl);

      this.socket.onopen = () => {
        console.log("WebSocket connected to OnlineAnnotator collaboration hub.");
        clearInterval(this.pingInterval);
        this.pingInterval = setInterval(() => {
          if (this.socket && this.socket.readyState === WebSocket.OPEN) {
            this.socket.send(JSON.stringify({ event: "PING" }));
          }
        }, 20000);
      };

      this.socket.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          if (payload.event === "PONG") return;

          // Dispatch event to app
          window.dispatchEvent(new CustomEvent("ws:event", { detail: payload }));
        } catch (_) {}
      };

      this.socket.onclose = () => {
        clearInterval(this.pingInterval);
        // Reconnect after delay
        setTimeout(() => this.connect(), 5000);
      };

      this.socket.onerror = () => {
        this.socket.close();
      };
    } catch (e) {
      console.warn("WebSocket connection skipped:", e);
    }
  },

  send(data) {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(data));
    }
  },
};

window.addEventListener("DOMContentLoaded", () => WS.init());
