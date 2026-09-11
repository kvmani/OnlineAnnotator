// HTTP client. All URLs are relative so the app also works behind a path prefix.
const CLIENT_HEADER = { "X-Requested-With": "OnlineAnnotator" };

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

let onUnauthorized = () => {};
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn;
}

async function parseError(response) {
  let message = `${response.status} ${response.statusText}`;
  try {
    const body = await response.json();
    if (body && body.detail) message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
  } catch (_) {
    /* not JSON */
  }
  return new ApiError(message, response.status);
}

export async function request(method, url, { json, body, headers = {}, raw = false } = {}) {
  const init = { method, credentials: "same-origin", headers: { ...CLIENT_HEADER, ...headers } };
  if (json !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(json);
  } else if (body !== undefined) {
    init.body = body;
  }
  let response;
  try {
    response = await fetch(url, init);
  } catch (err) {
    throw new ApiError("The server cannot be reached. Check your network connection; your work in this tab is kept.", 0);
  }
  if (response.status === 401 && !url.includes("auth/login") && !url.includes("auth/otp")) {
    onUnauthorized();
  }
  if (!response.ok) throw await parseError(response);
  if (raw) return response;
  const type = response.headers.get("content-type") || "";
  return type.includes("application/json") ? response.json() : response;
}

export const api = {
  get: (url) => request("GET", url),
  post: (url, json = {}) => request("POST", url, { json }),
  patch: (url, json = {}) => request("PATCH", url, { json }),
  del: (url) => request("DELETE", url),
  form: (url, formData) => request("POST", url, { body: formData }),
};

// Upload with progress (fetch has no upload progress events).
export function uploadWithProgress(url, formData, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.setRequestHeader("X-Requested-With", "OnlineAnnotator");
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      let data = {};
      try {
        data = JSON.parse(xhr.responseText);
      } catch (_) {
        /* ignore */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data);
      else reject(new ApiError(data.detail || `Upload failed (${xhr.status})`, xhr.status));
    };
    xhr.onerror = () => reject(new ApiError("Upload failed: the server cannot be reached.", 0));
    xhr.send(formData);
  });
}

// ---- label maps: raw bytes both ways, gzip on upload when the browser supports it
export async function fetchBytes(url) {
  const response = await request("GET", url, { raw: true });
  const buffer = await response.arrayBuffer();
  return { bytes: new Uint8Array(buffer), headers: response.headers };
}

async function gzip(bytes) {
  if (typeof CompressionStream === "undefined") return null;
  const stream = new Blob([bytes]).stream().pipeThrough(new CompressionStream("gzip"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

export async function putLabels(imageId, labels, baseRevision) {
  const compressed = await gzip(labels);
  const headers = { "Content-Type": "application/octet-stream" };
  if (compressed) headers["Content-Encoding"] = "gzip";
  return request("PUT", `api/v1/images/${imageId}/labels?base_revision=${baseRevision}`, {
    body: compressed || labels,
    headers,
  });
}

export function releaseLockBeacon(imageId) {
  try {
    navigator.sendBeacon(`api/v1/images/${imageId}/lock/release`);
  } catch (_) {
    /* best effort */
  }
}
