export type TimeUnit = 'minutes' | 'hours';

export interface ClientSession {
  remaining_seconds: number;
  time_limit: number;
  start_time?: string;
  end_time?: string;
}

export interface InternetSession {
  remaining_seconds: number;
  time_limit?: number;
  time_limit_seconds?: number;
  start_time?: string;
  end_time?: string;
  is_expired?: boolean;
}

export interface ClientConfig {
  sync_interval?: number;
  alert_thresholds?: number[];
  max_server_timeouts?: number;
  lock_recheck_interval?: number;
  custom_name?: string;
  network_filter_enabled?: boolean;
  internet_request_enabled?: boolean;
  allowlist?: string[];
  config_updated_at?: string;
}

export interface AccessRequest {
  id: string;
  client_id: string;
  domain: string;
  created_at?: string;
  status?: 'pending' | 'approved' | 'denied';
}

export interface Client {
  id: string;
  name: string;
  connected?: boolean;
  is_active?: boolean;
  current_session?: ClientSession | null;
  internet_session?: InternetSession | null;
  config?: ClientConfig;
  pending_access_requests?: AccessRequest[];
}

export interface ServerInfo {
  success: boolean;
  ip: string;
  port: number;
  url: string;
  broadcast_interval?: number;
}

export interface ServerConfig {
  broadcast_interval: number;
}

export interface KnownServer {
  url: string;
  ip?: string;
  port?: number;
  last_seen?: string;
}

export interface ApiResult {
  success: boolean;
  message?: string;
  config?: ClientConfig;
  known_servers?: KnownServer[];
  known_clients?: Client[];
  internet_session?: InternetSession;
}
