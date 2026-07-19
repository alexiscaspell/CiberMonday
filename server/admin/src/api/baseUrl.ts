import { Platform } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';

const STORAGE_KEY = 'cibermonday_server_base_url';
const DEFAULT_NATIVE = 'http://127.0.0.1:5000';

let cachedNativeUrl: string | null = null;

export function getWebOrigin(): string {
  if (typeof window !== 'undefined' && window.location?.host) {
    return `${window.location.protocol}//${window.location.host}`;
  }
  return '';
}

/** Base URL without trailing slash (origin only). */
export function getApiOrigin(): string {
  if (Platform.OS === 'web') {
    return getWebOrigin();
  }
  return cachedNativeUrl ?? DEFAULT_NATIVE;
}

export function apiUrl(path: string): string {
  const origin = getApiOrigin();
  const p = path.startsWith('/') ? path : `/${path}`;
  return `${origin}${p}`;
}

export async function loadStoredBaseUrl(): Promise<string> {
  if (Platform.OS === 'web') {
    return getWebOrigin();
  }
  try {
    const stored = await AsyncStorage.getItem(STORAGE_KEY);
    cachedNativeUrl = stored?.trim() || DEFAULT_NATIVE;
  } catch {
    cachedNativeUrl = DEFAULT_NATIVE;
  }
  return cachedNativeUrl;
}

export async function setStoredBaseUrl(url: string): Promise<void> {
  const cleaned = url.trim().replace(/\/$/, '');
  cachedNativeUrl = cleaned || DEFAULT_NATIVE;
  if (Platform.OS !== 'web') {
    await AsyncStorage.setItem(STORAGE_KEY, cachedNativeUrl);
  }
}

export function needsServerSetup(): boolean {
  return Platform.OS !== 'web';
}
