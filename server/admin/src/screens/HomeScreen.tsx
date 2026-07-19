import React, { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Platform,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { StatusBar } from 'expo-status-bar';
import * as api from '../api/client';
import {
  loadStoredBaseUrl,
  needsServerSetup,
  setStoredBaseUrl,
  getApiOrigin,
} from '../api/baseUrl';
import type { Client, KnownServer } from '../api/types';
import { ClientCard } from '../components/ClientCard';
import { ServersSection } from '../components/ServersSection';
import { Button } from '../components/Button';
import { colors, maxContentWidth, radius, spacing } from '../theme';

export function HomeScreen() {
  const [ready, setReady] = useState(false);
  const [setupUrl, setSetupUrl] = useState('http://127.0.0.1:5000');
  const [showSetup, setShowSetup] = useState(false);

  const [clients, setClients] = useState<Client[]>([]);
  const [servers, setServers] = useState<KnownServer[]>([]);
  const [serverUrl, setServerUrl] = useState('');
  const [broadcast, setBroadcast] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [broadcastDraft, setBroadcastDraft] = useState('');
  const [showBroadcastModal, setShowBroadcastModal] = useState(false);

  const notify = (msg: string) => {
    if (Platform.OS === 'web' && typeof window !== 'undefined') window.alert(msg);
    else Alert.alert('CiberMonday', msg);
  };

  useEffect(() => {
    (async () => {
      await loadStoredBaseUrl();
      if (needsServerSetup()) {
        const ok = await api.healthCheck();
        if (!ok) {
          setSetupUrl(getApiOrigin());
          setShowSetup(true);
        }
      }
      setReady(true);
    })();
  }, []);

  const loadAll = useCallback(async (withForceSync = false) => {
    setError(null);
    try {
      if (withForceSync) {
        try {
          const ctrl = new AbortController();
          const t = setTimeout(() => ctrl.abort(), 4000);
          await api.forceSync();
          clearTimeout(t);
        } catch {
          /* ignore sync errors */
        }
      }
      const [c, info, cfg, srv] = await Promise.all([
        api.fetchClients(),
        api.fetchServerInfo(),
        api.fetchServerConfig().catch(() => null),
        api.fetchServers(),
      ]);
      setClients(c);
      setServerUrl(info.url);
      setBroadcast(cfg?.broadcast_interval ?? info.broadcast_interval ?? null);
      setServers(srv);
    } catch (e: any) {
      setError(e.message || 'No se pudo conectar al servidor');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    if (!ready || showSetup) return;
    loadAll(false);
    const id = setInterval(() => loadAll(false), 5000);
    return () => clearInterval(id);
  }, [ready, showSetup, loadAll]);

  const onRefresh = async () => {
    setRefreshing(true);
    await loadAll(true);
  };

  const onCopyUrl = async () => {
    if (!serverUrl) return;
    try {
      if (Platform.OS === 'web' && typeof navigator !== 'undefined' && navigator.clipboard) {
        await navigator.clipboard.writeText(serverUrl);
        notify('URL copiada');
        return;
      }
      notify(serverUrl);
    } catch {
      notify(serverUrl);
    }
  };

  const applyBroadcast = async (raw: string) => {
    const n = parseInt(raw, 10);
    if (isNaN(n) || n < 1 || n > 300) {
      notify('Valor inválido (1-300)');
      return;
    }
    try {
      const res = await api.setServerConfig(n);
      if (res.success) {
        setBroadcast(n);
        setShowBroadcastModal(false);
        notify(`Broadcast: ${n}s`);
      } else notify(res.message || 'Error');
    } catch (e: any) {
      notify(e.message || 'Error');
    }
  };

  const onBroadcast = () => {
    const current = broadcast ?? 1;
    if (Platform.OS === 'web' && typeof window !== 'undefined') {
      const ask = window.prompt(
        `Intervalo de broadcast (1-300 seg). Actual: ${current}`,
        String(current),
      );
      if (ask != null) applyBroadcast(ask);
      return;
    }
    setBroadcastDraft(String(current));
    setShowBroadcastModal(true);
  };

  const saveSetup = async () => {
    await setStoredBaseUrl(setupUrl);
    const ok = await api.healthCheck();
    if (!ok) {
      notify('No hay respuesta en /api/health. Revisá la URL.');
      return;
    }
    setShowSetup(false);
    setLoading(true);
    await loadAll(false);
  };

  if (!ready) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" color={colors.primary} />
      </View>
    );
  }

  if (showSetup) {
    return (
      <View style={styles.centerPad}>
        <StatusBar style="dark" />
        <Text style={styles.setupTitle}>Servidor CiberMonday</Text>
        <Text style={styles.setupHint}>
          Ingresá la URL del servidor (en este teléfono usá 127.0.0.1 si el
          servicio local está activo).
        </Text>
        <TextInput
          style={styles.setupInput}
          value={setupUrl}
          onChangeText={setSetupUrl}
          autoCapitalize="none"
          placeholder="http://192.168.1.10:5000"
          placeholderTextColor={colors.muted}
        />
        <Button title="Conectar" onPress={saveSetup} />
      </View>
    );
  }

  return (
    <View style={styles.root}>
      <StatusBar style="dark" />
      <ScrollView
        contentContainerStyle={styles.scroll}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
        }
      >
        <View style={styles.content}>
          <View style={styles.header}>
            <Text style={styles.brand}>CiberMonday</Text>
            <Text style={styles.subtitle}>Panel de control</Text>
            <View style={styles.statusRow}>
              <View style={styles.statusDot} />
              <Text style={styles.statusText}>Servidor activo</Text>
              <Text style={styles.count}>{clients.length} clientes</Text>
            </View>
            <View style={styles.urlRow}>
              <Text style={styles.url} numberOfLines={1}>
                {serverUrl || '…'}
              </Text>
              <Button title="Copiar" compact onPress={onCopyUrl} />
            </View>
            <View style={styles.broadcastRow}>
              <Text style={styles.broadcastLabel}>
                Broadcast:{' '}
                <Text style={{ fontWeight: '700' }}>
                  {broadcast != null ? `${broadcast}s` : '…'}
                </Text>
              </Text>
              <Button title="Configurar" compact variant="ghost" onPress={onBroadcast} />
            </View>
            {needsServerSetup() ? (
              <Button
                title="Cambiar servidor"
                compact
                variant="ghost"
                onPress={() => {
                  setSetupUrl(getApiOrigin());
                  setShowSetup(true);
                }}
                style={{ marginTop: spacing.sm }}
              />
            ) : null}
          </View>

          {error ? (
            <View style={styles.errorBox}>
              <Text style={styles.errorText}>{error}</Text>
              <Button title="Reintentar" onPress={() => loadAll(false)} />
            </View>
          ) : null}

          <ServersSection
            servers={servers}
            currentUrl={serverUrl}
            onChanged={() => loadAll(false)}
          />

          {loading && clients.length === 0 ? (
            <ActivityIndicator color={colors.primary} style={{ marginTop: 40 }} />
          ) : clients.length === 0 ? (
            <Text style={styles.empty}>No hay clientes registrados</Text>
          ) : (
            clients.map((c) => (
              <ClientCard key={c.id} client={c} onChanged={() => loadAll(false)} />
            ))
          )}
        </View>
      </ScrollView>

      <Pressable style={styles.fab} onPress={onRefresh}>
        {refreshing ? (
          <ActivityIndicator color="#fff" />
        ) : (
          <Text style={styles.fabText}>↻</Text>
        )}
      </Pressable>

      {showBroadcastModal ? (
        <View style={styles.modalOverlay}>
          <View style={styles.modalCard}>
            <Text style={styles.setupTitle}>Broadcast (seg)</Text>
            <TextInput
              style={styles.setupInput}
              value={broadcastDraft}
              onChangeText={setBroadcastDraft}
              keyboardType="number-pad"
            />
            <View style={{ flexDirection: 'row', gap: spacing.sm }}>
              <Button
                title="Cancelar"
                variant="ghost"
                style={{ flex: 1 }}
                onPress={() => setShowBroadcastModal(false)}
              />
              <Button
                title="Guardar"
                style={{ flex: 1 }}
                onPress={() => applyBroadcast(broadcastDraft)}
              />
            </View>
          </View>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  scroll: { paddingBottom: 100, alignItems: 'center' },
  content: {
    width: '100%',
    maxWidth: maxContentWidth,
    padding: spacing.lg,
  },
  center: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.background,
  },
  centerPad: {
    flex: 1,
    justifyContent: 'center',
    padding: spacing.xl,
    backgroundColor: colors.background,
    gap: spacing.md,
  },
  setupTitle: { fontSize: 24, fontWeight: '800', color: colors.text },
  setupHint: { color: colors.textSecondary, marginBottom: spacing.sm },
  setupInput: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    padding: spacing.md,
    fontSize: 16,
    backgroundColor: colors.surface,
    color: colors.text,
  },
  header: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    padding: spacing.lg,
    marginBottom: spacing.lg,
    borderWidth: 1,
    borderColor: colors.border,
  },
  brand: { fontSize: 26, fontWeight: '900', color: colors.primary },
  subtitle: { color: colors.textSecondary, marginBottom: spacing.md },
  statusRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.md,
  },
  statusDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
    backgroundColor: colors.success,
  },
  statusText: { fontWeight: '700', color: colors.success },
  count: { marginLeft: 'auto', color: colors.textSecondary, fontWeight: '600' },
  urlRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.sm,
  },
  url: { flex: 1, fontWeight: '600', color: colors.text },
  broadcastRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: colors.background,
    borderRadius: radius.sm,
    padding: spacing.md,
  },
  broadcastLabel: { color: colors.text },
  errorBox: {
    backgroundColor: colors.dangerBg,
    padding: spacing.md,
    borderRadius: radius.sm,
    marginBottom: spacing.md,
    gap: spacing.sm,
  },
  errorText: { color: colors.danger, fontWeight: '600' },
  empty: {
    textAlign: 'center',
    color: colors.muted,
    marginTop: spacing.xl,
    fontSize: 16,
  },
  fab: {
    position: 'absolute',
    right: 24,
    bottom: 24,
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: colors.primary,
    alignItems: 'center',
    justifyContent: 'center',
    elevation: 4,
    shadowColor: '#000',
    shadowOpacity: 0.2,
    shadowRadius: 4,
    shadowOffset: { width: 0, height: 2 },
  },
  fabText: { color: '#fff', fontSize: 28, fontWeight: '700', lineHeight: 32 },
  modalOverlay: {
    ...StyleSheet.absoluteFill,
    backgroundColor: 'rgba(0,0,0,0.45)',
    justifyContent: 'center',
    padding: spacing.xl,
  },
  modalCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    padding: spacing.lg,
    gap: spacing.md,
  },
});
