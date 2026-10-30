import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Platform,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import type { Client, TimeUnit } from '../api/types';
import * as api from '../api/client';
import { colors, radius, spacing } from '../theme';
import { formatTime, shortId } from '../utils/format';
import { Button } from './Button';

type UnitOption = { value: TimeUnit; label: string };

type AllowlistRow =
  | { kind: 'rule'; lineIndex: number; domain: string; enabled: boolean }
  | { kind: 'section'; lineIndex: number; label: string };

const RULE_TOKEN =
  /^(?:\*\.)?(?:(?:\d{1,3}\.){3}\d{1,3}(?:\/\d{1,2})?|(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,})$/i;

function looksLikeAllowRule(token: string): boolean {
  return RULE_TOKEN.test(token.trim());
}

/** Parsea texto allowlist estilo hosts (reglas, # deshabilitadas, secciones). */
function parseAllowlistRows(text: string): AllowlistRow[] {
  const rows: AllowlistRow[] = [];
  const lines = text.split('\n');
  lines.forEach((raw, lineIndex) => {
    const line = raw.trim();
    if (!line) return;
    if (line.startsWith('#')) {
      const rest = line.slice(1).trim();
      const token = rest.split(/\s+/)[0] || '';
      if (looksLikeAllowRule(token)) {
        rows.push({
          kind: 'rule',
          lineIndex,
          domain: token.toLowerCase(),
          enabled: false,
        });
      } else {
        rows.push({ kind: 'section', lineIndex, label: rest || line });
      }
      return;
    }
    const beforeComment = line.includes('#')
      ? line.slice(0, line.indexOf('#')).trim()
      : line;
    if (!beforeComment) return;
    const token = beforeComment.split(/\s+/)[0] || '';
    if (!looksLikeAllowRule(token)) return;
    rows.push({
      kind: 'rule',
      lineIndex,
      domain: token.toLowerCase(),
      enabled: true,
    });
  });
  return rows;
}

function toggleAllowlistLine(text: string, lineIndex: number): string {
  const lines = text.split('\n');
  if (lineIndex < 0 || lineIndex >= lines.length) return text;
  const raw = lines[lineIndex];
  const trimmed = raw.trim();
  if (!trimmed) return text;
  const indent = raw.match(/^\s*/)?.[0] ?? '';
  if (trimmed.startsWith('#')) {
    const rest = trimmed.slice(1).trim();
    const token = rest.split(/\s+/)[0] || '';
    if (!looksLikeAllowRule(token)) return text;
    lines[lineIndex] = `${indent}${token.toLowerCase()}`;
  } else {
    const beforeComment = trimmed.includes('#')
      ? trimmed.slice(0, trimmed.indexOf('#')).trim()
      : trimmed;
    const token = beforeComment.split(/\s+/)[0] || '';
    if (!looksLikeAllowRule(token)) return text;
    lines[lineIndex] = `${indent}# ${token.toLowerCase()}`;
  }
  return lines.join('\n');
}

/** Desplegable nativo en web/WebView (los botones Pressable fallan en Android WebView). */
function UnitDropdown({
  unit,
  onChange,
  options,
}: {
  unit: TimeUnit;
  onChange: (u: TimeUnit) => void;
  options: UnitOption[];
}) {
  if (Platform.OS === 'web') {
    return (
      <View style={styles.selectWrap}>
        {React.createElement(
          'select',
          {
            value: unit,
            onChange: (e: { target: { value: string } }) => {
              onChange(e.target.value as TimeUnit);
            },
            style: {
              width: '100%',
              height: 44,
              minHeight: 44,
              fontSize: 16,
              fontWeight: '700',
              color: colors.text,
              backgroundColor: colors.surface,
              border: `1px solid ${colors.border}`,
              borderRadius: radius.sm,
              paddingLeft: 10,
              paddingRight: 10,
            },
            'aria-label': 'Unidad de tiempo',
          },
          options.map((o) =>
            React.createElement('option', { key: o.value, value: o.value }, o.label),
          ),
        )}
      </View>
    );
  }

  // Fallback nativo (Expo app): lista simple
  return (
    <View style={styles.selectWrap}>
      {options.map((o) => (
        <Button
          key={o.value}
          title={o.label}
          compact
          variant={unit === o.value ? 'primary' : 'ghost'}
          onPress={() => onChange(o.value)}
        />
      ))}
    </View>
  );
}

interface Props {
  client: Client;
  onChanged: () => void;
}

export function ClientCard({ client, onChanged }: Props) {
  const session = client.current_session ?? null;
  const hasSession = session != null;
  const expired = hasSession && (session?.remaining_seconds ?? 0) <= 0;
  const internetSession = client.internet_session ?? null;
  const hasInternetSession = internetSession != null;
  const internetExpired =
    hasInternetSession && (internetSession?.remaining_seconds ?? 0) <= 0;
  const deviceSessionActive = hasSession && !expired;

  const [time, setTime] = useState('60');
  const [unit, setUnit] = useState<TimeUnit>('minutes');
  const [internetTime, setInternetTime] = useState('30');
  const [internetUnit, setInternetUnit] = useState<TimeUnit>('minutes');
  const [showConfig, setShowConfig] = useState(false);
  const [editingName, setEditingName] = useState(false);
  const [nameDraft, setNameDraft] = useState(client.name);
  const [busy, setBusy] = useState(false);

  const [syncInterval, setSyncInterval] = useState(
    String(client.config?.sync_interval ?? 30),
  );
  const [alerts, setAlerts] = useState(
    (client.config?.alert_thresholds ?? [600, 300, 120, 60])
      .map((s) => s / 60)
      .join(', '),
  );
  const [timeouts, setTimeouts] = useState(
    String(client.config?.max_server_timeouts ?? 10),
  );
  const [lockRecheck, setLockRecheck] = useState(
    String(client.config?.lock_recheck_interval ?? 1),
  );
  const [networkFilter, setNetworkFilter] = useState(
    !!client.config?.network_filter_enabled,
  );
  const [internetRequest, setInternetRequest] = useState(
    !!client.config?.internet_request_enabled,
  );
  const [allowlistText, setAllowlistText] = useState(
    (client.config?.allowlist ?? []).join('\n'),
  );
  const [configStatus, setConfigStatus] = useState('');
  // Evita que el poll pise ediciones locales; al guardar se limpia.
  const [configDirty, setConfigDirty] = useState(false);

  // Poll / sync peer: reflejar config del server (allowlist/filter incluidos).
  useEffect(() => {
    if (configDirty) return;
    const cfg = client.config;
    setSyncInterval(String(cfg?.sync_interval ?? 30));
    setAlerts(
      (cfg?.alert_thresholds ?? [600, 300, 120, 60]).map((s) => s / 60).join(', '),
    );
    setTimeouts(String(cfg?.max_server_timeouts ?? 10));
    setLockRecheck(String(cfg?.lock_recheck_interval ?? 1));
    setNetworkFilter(!!cfg?.network_filter_enabled);
    setInternetRequest(!!cfg?.internet_request_enabled);
    setAllowlistText((cfg?.allowlist ?? []).join('\n'));
  }, [
    configDirty,
    client.config?.config_updated_at,
    client.config?.network_filter_enabled,
    client.config?.internet_request_enabled,
    client.config?.sync_interval,
    client.config?.max_server_timeouts,
    client.config?.lock_recheck_interval,
    JSON.stringify(client.config?.alert_thresholds ?? null),
    JSON.stringify(client.config?.allowlist ?? null),
  ]);

  const connected = !!client.connected;
  const pendingRequests = client.pending_access_requests ?? [];
  const allowlistRows = useMemo(
    () => parseAllowlistRows(allowlistText),
    [allowlistText],
  );

  const notify = (msg: string) => {
    if (Platform.OS === 'web' && typeof window !== 'undefined') {
      window.alert(msg);
    } else {
      Alert.alert('CiberMonday', msg);
    }
  };

  const confirm = (msg: string): Promise<boolean> =>
    new Promise((resolve) => {
      if (Platform.OS === 'web' && typeof window !== 'undefined') {
        resolve(window.confirm(msg));
        return;
      }
      Alert.alert('Confirmar', msg, [
        { text: 'Cancelar', style: 'cancel', onPress: () => resolve(false) },
        { text: 'OK', onPress: () => resolve(true) },
      ]);
    });

  const onSetTime = async () => {
    const value = parseInt(time, 10);
    if (!value || value < 1) {
      notify('Ingresá un tiempo válido');
      return;
    }
    setBusy(true);
    try {
      const res = await api.setClientTime(client.id, value, unit);
      if (!res.success) notify(res.message || 'Error');
      onChanged();
    } catch (e: any) {
      notify(e.message || 'Error al establecer tiempo');
    } finally {
      setBusy(false);
    }
  };

  const onStop = async () => {
    // En WebView Android, window.confirm a veces falla; no bloquear Detener
    const ok =
      Platform.OS === 'web'
        ? true
        : await confirm(`¿Detener sesión de ${client.name}?`);
    if (!ok) return;
    setBusy(true);
    try {
      await api.stopClient(client.id);
      onChanged();
    } catch (e: any) {
      notify(e.message || 'Error al detener');
    } finally {
      setBusy(false);
    }
  };

  const onSetInternetTime = async () => {
    if (!deviceSessionActive) {
      notify('Primero establecê una sesión de dispositivo activa');
      return;
    }
    const value = parseInt(internetTime, 10);
    if (!value || value < 1) {
      notify('Ingresá un tiempo de internet válido');
      return;
    }
    setBusy(true);
    try {
      const res = await api.setClientInternetTime(client.id, value, internetUnit);
      if (!res.success) notify(res.message || 'Error');
      onChanged();
    } catch (e: any) {
      notify(e.message || 'Error al establecer tiempo de internet');
    } finally {
      setBusy(false);
    }
  };

  const onStopInternet = async () => {
    setBusy(true);
    try {
      await api.stopClientInternet(client.id);
      onChanged();
    } catch (e: any) {
      notify(e.message || 'Error al detener internet');
    } finally {
      setBusy(false);
    }
  };

  const onDelete = async () => {
    if (!(await confirm(`¿Eliminar cliente ${client.name}?`))) return;
    setBusy(true);
    try {
      await api.deleteClient(client.id);
      onChanged();
    } catch (e: any) {
      notify(e.message || 'Error al eliminar');
    } finally {
      setBusy(false);
    }
  };

  const onSaveName = async () => {
    const trimmed = nameDraft.trim();
    if (!trimmed || trimmed === client.name) {
      setEditingName(false);
      return;
    }
    setBusy(true);
    try {
      const res = await api.setClientConfig(client.id, { custom_name: trimmed });
      if (!res.success) notify(res.message || 'Error');
      setEditingName(false);
      onChanged();
    } catch (e: any) {
      notify(e.message || 'Error al renombrar');
    } finally {
      setBusy(false);
    }
  };

  const onSaveConfig = async () => {
    const sync = parseInt(syncInterval, 10);
    const maxT = parseInt(timeouts, 10);
    const lock = parseInt(lockRecheck, 10);
    const alertMinutes = alerts
      .split(',')
      .map((s) => parseFloat(s.trim()))
      .filter((n) => !isNaN(n) && n > 0);
    const alertThresholds = alertMinutes.map((m) => Math.round(m * 60));

    if (sync < 5) {
      notify('El intervalo de sincronización mínimo es 5 segundos');
      return;
    }
    if (alertThresholds.length === 0) {
      notify('Debés especificar al menos un umbral de alerta');
      return;
    }
    if (isNaN(maxT) || maxT < 1 || maxT > 100) {
      notify('Reintentos deben estar entre 1 y 100');
      return;
    }
    if (isNaN(lock) || lock < 1 || lock > 60) {
      notify('Re-bloqueo debe estar entre 1 y 60 segundos');
      return;
    }

    // Conserva # dominio (deshabilitado) y # secciones; el server normaliza.
    const allowlist = allowlistText
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean);

    setBusy(true);
    try {
      const res = await api.setClientConfig(client.id, {
        sync_interval: sync,
        alert_thresholds: alertThresholds,
        max_server_timeouts: maxT,
        lock_recheck_interval: lock,
        network_filter_enabled: networkFilter,
        internet_request_enabled: networkFilter && internetRequest,
        allowlist,
      });
      if (res.success) {
        setConfigStatus('Guardado');
        setConfigDirty(false);
        if (res.config?.alert_thresholds) {
          setAlerts(res.config.alert_thresholds.map((s) => s / 60).join(', '));
        }
        if (res.config?.allowlist) {
          setAllowlistText(res.config.allowlist.join('\n'));
        }
        if (typeof res.config?.network_filter_enabled === 'boolean') {
          setNetworkFilter(res.config.network_filter_enabled);
        }
        if (typeof res.config?.internet_request_enabled === 'boolean') {
          setInternetRequest(res.config.internet_request_enabled);
        }
        setTimeout(() => setConfigStatus(''), 2500);
        onChanged();
      } else {
        notify(res.message || 'Error');
      }
    } catch (e: any) {
      notify(e.message || 'Error al guardar config');
    } finally {
      setBusy(false);
    }
  };

  const onApproveAccess = async (requestId: string) => {
    setBusy(true);
    try {
      const res = await api.approveAccessRequest(client.id, requestId);
      if (res.success) {
        if (res.config?.allowlist) {
          setAllowlistText(res.config.allowlist.join('\n'));
        }
        notify(res.message || 'Aprobado');
        onChanged();
      } else {
        notify(res.message || 'Error al aprobar');
      }
    } catch (e: any) {
      notify(e.message || 'Error al aprobar');
    } finally {
      setBusy(false);
    }
  };

  const onDenyAccess = async (requestId: string) => {
    setBusy(true);
    try {
      const res = await api.denyAccessRequest(client.id, requestId);
      if (res.success) {
        notify(res.message || 'Rechazado');
        onChanged();
      } else {
        notify(res.message || 'Error al rechazar');
      }
    } catch (e: any) {
      notify(e.message || 'Error al rechazar');
    } finally {
      setBusy(false);
    }
  };

  const unitOptions = useMemo<UnitOption[]>(
    () => [
      { value: 'minutes', label: 'Minutos' },
      { value: 'hours', label: 'Horas' },
    ],
    [],
  );

  return (
    <View style={styles.card}>
      <View style={styles.header}>
        <View style={{ flex: 1 }}>
          {editingName ? (
            <View style={styles.nameRow}>
              <TextInput
                style={styles.nameInput}
                value={nameDraft}
                onChangeText={setNameDraft}
                maxLength={50}
                autoFocus
              />
              <Button title="OK" compact onPress={onSaveName} disabled={busy} />
              <Button
                title="X"
                compact
                variant="ghost"
                onPress={() => {
                  setNameDraft(client.name);
                  setEditingName(false);
                }}
              />
            </View>
          ) : (
            <View style={styles.nameRow}>
              <Text style={styles.name}>{client.name || 'Sin nombre'}</Text>
              <Button
                title="Editar"
                compact
                variant="ghost"
                onPress={() => {
                  setNameDraft(client.name);
                  setEditingName(true);
                }}
              />
            </View>
          )}
          <Text style={styles.id}>ID: {shortId(client.id)}</Text>
        </View>
        <View
          style={[
            styles.chip,
            connected ? styles.chipOn : styles.chipOff,
          ]}
        >
          <Text
            style={[
              styles.chipText,
              { color: connected ? colors.success : colors.muted },
            ]}
          >
            {connected ? 'CONECTADO' : 'OFFLINE'}
          </Text>
        </View>
      </View>

      {hasSession && session && (
        <View style={styles.session}>
          <Text style={styles.sessionLabel}>
            Asignado: {formatTime(session.time_limit)}
          </Text>
          <Text style={[styles.remaining, expired && styles.expired]}>
            {formatTime(session.remaining_seconds)}
          </Text>
          {session.start_time ? (
            <Text style={styles.sessionLabel}>
              Inicio: {new Date(session.start_time).toLocaleTimeString()}
            </Text>
          ) : null}
        </View>
      )}

      {hasInternetSession && internetSession && (
        <View style={styles.session}>
          <Text style={styles.sessionLabel}>Internet</Text>
          <Text style={[styles.remainingInternet, internetExpired && styles.expired]}>
            {formatTime(internetSession.remaining_seconds)}
          </Text>
        </View>
      )}

      <View style={styles.timeRow}>
        <TextInput
          style={[styles.input, { flex: 1 }]}
          keyboardType="number-pad"
          value={time}
          onChangeText={setTime}
          placeholder="Tiempo"
          placeholderTextColor={colors.muted}
        />
        <UnitDropdown unit={unit} onChange={setUnit} options={unitOptions} />
      </View>
      <View style={styles.primaryActions}>
        <Button
          title="Establecer tiempo"
          onPress={onSetTime}
          loading={busy}
          style={{ flex: 1 }}
        />
        <Button
          title="Detener"
          variant="secondary"
          onPress={onStop}
          disabled={busy}
          style={{ flex: 1 }}
        />
      </View>

      <Text style={[styles.fieldLabel, { marginTop: spacing.md }]}>
        Tiempo de internet (opcional)
      </Text>
      <View style={styles.timeRow}>
        <TextInput
          style={[styles.input, { flex: 1 }]}
          keyboardType="number-pad"
          value={internetTime}
          onChangeText={setInternetTime}
          placeholder="Internet"
          placeholderTextColor={colors.muted}
          editable={deviceSessionActive}
        />
        <UnitDropdown
          unit={internetUnit}
          onChange={setInternetUnit}
          options={unitOptions}
        />
      </View>
      <View style={styles.primaryActions}>
        <Button
          title="Establecer internet"
          onPress={onSetInternetTime}
          loading={busy}
          disabled={!deviceSessionActive}
          style={{ flex: 1 }}
        />
        <Button
          title="Detener internet"
          variant="secondary"
          onPress={onStopInternet}
          disabled={busy || !hasInternetSession}
          style={{ flex: 1 }}
        />
      </View>

      <View style={styles.actions}>
        <Button
          title="Eliminar"
          variant="danger"
          onPress={onDelete}
          disabled={busy}
          style={{ flex: 1 }}
        />
      </View>

      <Button
        title={showConfig ? 'Ocultar configuración' : 'Configuración'}
        variant="ghost"
        onPress={() => setShowConfig((v) => !v)}
        style={{ marginTop: spacing.md }}
      />

      {showConfig && (
        <View style={styles.config}>
          <Field
            label="Sincronización (seg)"
            value={syncInterval}
            onChange={(v) => {
              setConfigDirty(true);
              setSyncInterval(v);
            }}
            keyboard="number-pad"
          />
          <Field
            label="Alertas (min, coma)"
            value={alerts}
            onChange={(v) => {
              setConfigDirty(true);
              setAlerts(v);
            }}
          />
          <Field
            label="Reintentos servidor"
            value={timeouts}
            onChange={(v) => {
              setConfigDirty(true);
              setTimeouts(v);
            }}
            keyboard="number-pad"
          />
          <Field
            label="Re-bloqueo (seg)"
            value={lockRecheck}
            onChange={(v) => {
              setConfigDirty(true);
              setLockRecheck(v);
            }}
            keyboard="number-pad"
          />
          <View style={styles.toggleRow}>
            <Text style={styles.fieldLabel}>Filtrar internet (allowlist)</Text>
            <Button
              title={networkFilter ? 'Activado' : 'Desactivado'}
              compact
              variant={networkFilter ? 'primary' : 'ghost'}
              onPress={() => {
                setConfigDirty(true);
                setNetworkFilter((v) => !v);
              }}
            />
          </View>
          <View style={styles.toggleRow}>
            <Text style={styles.fieldLabel}>Pedir acceso (notificar)</Text>
            <Button
              title={internetRequest ? 'Activado' : 'Desactivado'}
              compact
              variant={internetRequest ? 'primary' : 'ghost'}
              disabled={!networkFilter}
              onPress={() => {
                setConfigDirty(true);
                setInternetRequest((v) => !v);
              }}
            />
          </View>
          <Text style={styles.hint}>
            Si está activado, el cliente avisa cuando intenta un dominio fuera
            de la allowlist; podés aprobarlo acá (queda permanente).
          </Text>
          {pendingRequests.length > 0 ? (
            <View style={styles.accessReqBox}>
              <Text style={styles.fieldLabel}>Pedidos de acceso</Text>
              {pendingRequests.map((req) => (
                <View key={req.id} style={styles.accessReqRow}>
                  <Text style={styles.allowlistRuleText} numberOfLines={1}>
                    {req.domain}
                  </Text>
                  <View style={styles.accessReqActions}>
                    <Button
                      title="Aprobar"
                      compact
                      variant="success"
                      disabled={busy}
                      onPress={() => onApproveAccess(req.id)}
                    />
                    <Button
                      title="Rechazar"
                      compact
                      variant="ghost"
                      disabled={busy}
                      onPress={() => onDenyAccess(req.id)}
                    />
                  </View>
                </View>
              ))}
            </View>
          ) : null}
          <Text style={styles.fieldLabel}>
            Allowlist (uno por línea; # desactiva o comenta)
          </Text>
          <Text style={styles.hint}>
            Solo lo listado (y subdominios / *.wildcards). Los CDN u otros
            hosts que el sitio pide al navegar se aprenden solos en segundo
            plano (no se listan acá). “Pedir acceso” es para sitios que el
            usuario intenta abrir fuera de la allowlist.
            Usá On/Off para desactivar una regla sin borrarla.
          </Text>
          <TextInput
            style={[styles.input, styles.allowlistInput]}
            value={allowlistText}
            onChangeText={(t) => {
              setConfigDirty(true);
              setAllowlistText(t);
            }}
            multiline
            numberOfLines={8}
            placeholder={
              '# === ejemplo ===\nyoutube.com\n# ssl.gstatic.com\n*.khanacademy.org'
            }
            placeholderTextColor={colors.muted}
            editable={networkFilter}
          />
          {allowlistRows.length > 0 ? (
            <View style={styles.allowlistRules}>
              {allowlistRows.map((row) =>
                row.kind === 'section' ? (
                  <Text key={`s-${row.lineIndex}`} style={styles.allowlistSection}>
                    {row.label}
                  </Text>
                ) : (
                  <View key={`r-${row.lineIndex}`} style={styles.allowlistRuleRow}>
                    <Text
                      style={[
                        styles.allowlistRuleText,
                        !row.enabled && styles.allowlistRuleOff,
                      ]}
                      numberOfLines={1}
                    >
                      {row.domain}
                    </Text>
                    <Button
                      title={row.enabled ? 'On' : 'Off'}
                      compact
                      variant={row.enabled ? 'primary' : 'ghost'}
                      disabled={!networkFilter}
                      onPress={() => {
                        setConfigDirty(true);
                        setAllowlistText((t) =>
                          toggleAllowlistLine(t, row.lineIndex),
                        );
                      }}
                    />
                  </View>
                ),
              )}
            </View>
          ) : null}
          <Button title="Guardar configuración" onPress={onSaveConfig} loading={busy} />
          {configStatus ? (
            <Text style={styles.configOk}>{configStatus}</Text>
          ) : null}
        </View>
      )}
    </View>
  );
}

function Field({
  label,
  value,
  onChange,
  keyboard,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  keyboard?: 'number-pad' | 'default';
}) {
  return (
    <View style={{ marginBottom: spacing.md }}>
      <Text style={styles.fieldLabel}>{label}</Text>
      <TextInput
        style={styles.input}
        value={value}
        onChangeText={onChange}
        keyboardType={keyboard || 'default'}
        placeholderTextColor={colors.muted}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    padding: spacing.lg,
    marginBottom: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.sm,
    marginBottom: spacing.md,
  },
  nameRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    flexWrap: 'wrap',
  },
  name: {
    fontSize: 18,
    fontWeight: '700',
    color: colors.text,
  },
  nameInput: {
    flex: 1,
    minWidth: 120,
    borderWidth: 1,
    borderColor: colors.primary,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    fontSize: 16,
    fontWeight: '700',
    color: colors.text,
  },
  id: {
    fontSize: 12,
    color: colors.textSecondary,
    fontFamily: Platform.select({ ios: 'Menlo', android: 'monospace', default: 'monospace' }),
    marginTop: 2,
  },
  chip: {
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    borderRadius: radius.full,
  },
  chipOn: { backgroundColor: colors.successBg },
  chipOff: { backgroundColor: colors.chipInactive },
  chipText: { fontSize: 11, fontWeight: '800' },
  session: {
    backgroundColor: colors.background,
    borderRadius: radius.sm,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  sessionLabel: { fontSize: 12, color: colors.textSecondary },
  remaining: {
    fontSize: 28,
    fontWeight: '800',
    color: colors.primary,
    marginVertical: spacing.xs,
  },
  remainingInternet: {
    fontSize: 22,
    fontWeight: '800',
    color: colors.text,
    marginVertical: spacing.xs,
  },
  expired: { color: colors.danger },
  toggleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.md,
    gap: spacing.sm,
  },
  hint: {
    fontSize: 12,
    color: colors.muted,
    marginBottom: spacing.sm,
  },
  allowlistInput: {
    minHeight: 110,
    textAlignVertical: 'top',
    marginBottom: spacing.sm,
    fontFamily: Platform.select({
      ios: 'Menlo',
      android: 'monospace',
      default: 'monospace',
    }),
  },
  allowlistRules: {
    marginBottom: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    overflow: 'hidden',
  },
  allowlistSection: {
    fontSize: 11,
    fontWeight: '800',
    color: colors.muted,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
    backgroundColor: colors.background,
    textTransform: 'uppercase',
  },
  allowlistRuleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
  },
  allowlistRuleText: {
    flex: 1,
    fontSize: 13,
    fontWeight: '600',
    color: colors.text,
    fontFamily: Platform.select({
      ios: 'Menlo',
      android: 'monospace',
      default: 'monospace',
    }),
  },
  allowlistRuleOff: {
    color: colors.muted,
    textDecorationLine: 'line-through',
  },
  accessReqBox: {
    marginBottom: spacing.md,
    borderWidth: 1,
    borderColor: colors.primary,
    borderRadius: radius.sm,
    padding: spacing.sm,
    backgroundColor: colors.background,
  },
  accessReqRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.sm,
    marginTop: spacing.xs,
  },
  accessReqActions: {
    flexDirection: 'row',
    gap: spacing.xs,
    flexShrink: 0,
  },
  timeRow: {
    flexDirection: 'row',
    gap: spacing.sm,
    alignItems: 'stretch',
  },
  selectWrap: {
    width: 130,
    justifyContent: 'center',
  },
  input: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    fontSize: 16,
    color: colors.text,
    backgroundColor: colors.surface,
    minHeight: 44,
  },
  primaryActions: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginTop: spacing.sm,
  },
  actions: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginTop: spacing.md,
  },
  config: {
    marginTop: spacing.md,
    paddingTop: spacing.md,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  fieldLabel: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.textSecondary,
    marginBottom: spacing.xs,
  },
  configOk: {
    marginTop: spacing.sm,
    color: colors.success,
    fontWeight: '700',
    textAlign: 'center',
  },
});
