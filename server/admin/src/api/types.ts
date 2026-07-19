export type TimeUnit = 'minutes' | 'hours';

export interface ClientSession {
  remaining_seconds: number;
  time_limit: number;
  start_time?: string;
}

export interface ClientConfig {
  sync_interval?: number;
  alert_thresholds?: number[];
  max_server_timeouts?: number;
  lock_recheck_interval?: number;
  custom_name?: string;
}

export interface Client {
  id: string;
  name: string;
  connected?: boolean;
  is_active?: boolean;
  current_session?: ClientSession | null;
  config?: ClientConfig;
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
}
