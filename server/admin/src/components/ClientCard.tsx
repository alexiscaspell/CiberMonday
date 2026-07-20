import React, { useMemo, useState } from 'react';
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

  const [time, setTime] = useState('60');
  const [unit, setUnit] = useState<TimeUnit>('minutes');
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
  const [configStatus, setConfigStatus] = useState('');

  const connected = !!client.connected;

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

    setBusy(true);
    try {
      const res = await api.setClientConfig(client.id, {
        sync_interval: sync,
        alert_thresholds: alertThresholds,
        max_server_timeouts: maxT,
        lock_recheck_interval: lock,
      });
      if (res.success) {
        setConfigStatus('Guardado');
        if (res.config?.alert_thresholds) {
          setAlerts(res.config.alert_thresholds.map((s) => s / 60).join(', '));
        }
        setTimeout(() => setConfigStatus(''), 2500);
      } else {
        notify(res.message || 'Error');
      }
    } catch (e: any) {
      notify(e.message || 'Error al guardar config');
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
            onChange={setSyncInterval}
            keyboard="number-pad"
          />
          <Field
            label="Alertas (min, coma)"
            value={alerts}
            onChange={setAlerts}
          />
          <Field
            label="Reintentos servidor"
            value={timeouts}
            onChange={setTimeouts}
            keyboard="number-pad"
          />
          <Field
            label="Re-bloqueo (seg)"
            value={lockRecheck}
            onChange={setLockRecheck}
            keyboard="number-pad"
          />
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
  expired: { color: colors.danger },
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
