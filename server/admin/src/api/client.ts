import { apiUrl } from './baseUrl';
import type {
  ApiResult,
  Client,
  ClientConfig,
  KnownServer,
  ServerConfig,
  ServerInfo,
  TimeUnit,
} from './types';

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers: HeadersInit = {
    Accept: 'application/json',
    ...(options.body ? { 'Content-Type': 'application/json' } : {}),
    ...(options.headers || {}),
  };

  const res = await fetch(apiUrl(path), { ...options, headers });
  const data = await res.json().catch(() => ({}));
  if (!res.ok && data?.success === false) {
    throw new Error(data.message || `HTTP ${res.status}`);
  }
  return data as T;
}

export async function fetchClients(): Promise<Client[]> {
  const data = await request<{ success: boolean; clients: Client[] }>('/api/clients');
  return data.clients || [];
}

export async function fetchServerInfo(): Promise<ServerInfo> {
  return request<ServerInfo>('/api/server-info');
}

export async function fetchServerConfig(): Promise<ServerConfig> {
  const data = await request<{ success: boolean; config: ServerConfig }>('/api/server-config');
  return data.config;
}

export async function setServerConfig(broadcast_interval: number): Promise<ApiResult> {
  return request<ApiResult>('/api/server-config', {
    method: 'POST',
    body: JSON.stringify({ broadcast_interval }),
  });
}

export async function fetchServers(): Promise<KnownServer[]> {
  const data = await request<{ success: boolean; servers: KnownServer[] }>('/api/servers');
  return data.servers || [];
}

export async function registerServer(url: string, ip?: string, port?: number): Promise<ApiResult> {
  return request<ApiResult>('/api/register-server', {
    method: 'POST',
    body: JSON.stringify({ url, ip, port }),
  });
}

export async function forceSync(): Promise<ApiResult> {
  return request<ApiResult>('/api/force-sync', { method: 'POST' });
}

export async function setClientTime(
  clientId: string,
  time: number,
  unit: TimeUnit,
): Promise<ApiResult> {
  return request<ApiResult>(`/api/client/${clientId}/set-time`, {
    method: 'POST',
    body: JSON.stringify({ time, unit }),
  });
}

export async function stopClient(clientId: string): Promise<ApiResult> {
  return request<ApiResult>(`/api/client/${clientId}/stop`, { method: 'POST' });
}

export async function deleteClient(clientId: string): Promise<ApiResult> {
  return request<ApiResult>(`/api/client/${clientId}`, { method: 'DELETE' });
}

export async function setClientConfig(
  clientId: string,
  config: Partial<ClientConfig> & { custom_name?: string },
): Promise<ApiResult> {
  return request<ApiResult>(`/api/client/${clientId}/config`, {
    method: 'POST',
    body: JSON.stringify(config),
  });
}

export async function healthCheck(): Promise<boolean> {
  try {
    const data = await request<{ status: string }>('/api/health');
    return data.status === 'ok';
  } catch {
    return false;
  }
}
