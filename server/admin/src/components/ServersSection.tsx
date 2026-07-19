import React, { useState } from 'react';
import {
  Alert,
  Linking,
  Platform,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import type { KnownServer } from '../api/types';
import * as api from '../api/client';
import { colors, radius, spacing } from '../theme';
import { Button } from './Button';

interface Props {
  servers: KnownServer[];
  currentUrl: string;
  onChanged: () => void;
}

export function ServersSection({ servers, currentUrl, onChanged }: Props) {
  const [open, setOpen] = useState(false);
  const [adding, setAdding] = useState(false);
  const [urlDraft, setUrlDraft] = useState('http://');

  const others = servers.filter((s) => s.url !== currentUrl);

  const notify = (msg: string) => {
    if (Platform.OS === 'web' && typeof window !== 'undefined') window.alert(msg);
    else Alert.alert('CiberMonday', msg);
  };

  const onAdd = async () => {
    const url = urlDraft.trim();
    if (!url.startsWith('http://') && !url.startsWith('https://')) {
      notify('La URL debe comenzar con http:// o https://');
      return;
    }
    let ip: string | undefined;
    let port = 5000;
    try {
      const u = new URL(url);
      ip = u.hostname;
      port = u.port ? parseInt(u.port, 10) : 5000;
    } catch {
      /* ignore */
    }
    try {
      const res = await api.registerServer(url, ip, port);
      if (res.success) {
        setAdding(false);
        setUrlDraft('http://');
        onChanged();
        notify(`Servidor ${url} agregado`);
      } else {
        notify(res.message || 'No se pudo agregar');
      }
    } catch (e: any) {
      notify(e.message || 'Error');
    }
  };

  return (
    <View style={styles.wrap}>
      <Button
        title={open ? 'Ocultar servidores' : 'Ver servidores conocidos'}
        variant={open ? 'secondary' : 'primary'}
        onPress={() => setOpen((v) => !v)}
      />

      {open && (
        <View style={styles.panel}>
          <View style={styles.panelHeader}>
            <Text style={styles.title}>Otros servidores</Text>
            <Button
              title="Agregar"
              compact
              variant="success"
              onPress={() => setAdding((v) => !v)}
            />
          </View>

          {adding && (
            <View style={styles.addRow}>
              <TextInput
                style={styles.input}
                value={urlDraft}
                onChangeText={setUrlDraft}
                placeholder="http://192.168.0.3:5000"
                placeholderTextColor={colors.muted}
                autoCapitalize="none"
              />
              <Button title="Guardar" onPress={onAdd} />
            </View>
          )}

          {others.length === 0 ? (
            <Text style={styles.empty}>
              No hay otros servidores. Usá Agregar para registrar uno.
            </Text>
          ) : (
            others.map((s) => (
              <View key={s.url} style={styles.item}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.url}>{s.url}</Text>
                  {s.ip ? (
                    <Text style={styles.meta}>
                      IP: {s.ip}:{s.port || 5000}
                    </Text>
                  ) : null}
                  <Text style={styles.meta}>
                    Visto:{' '}
                    {s.last_seen
                      ? new Date(s.last_seen).toLocaleString()
                      : 'N/A'}
                  </Text>
                </View>
                <Button
                  title="Abrir"
                  compact
                  variant="success"
                  onPress={() => Linking.openURL(s.url)}
                />
              </View>
            ))
          )}
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { marginBottom: spacing.lg },
  panel: {
    marginTop: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    padding: spacing.lg,
    borderWidth: 1,
    borderColor: colors.border,
  },
  panelHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.md,
  },
  title: { fontSize: 16, fontWeight: '700', color: colors.text },
  addRow: { gap: spacing.sm, marginBottom: spacing.md },
  input: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    fontSize: 15,
    color: colors.text,
    minHeight: 44,
  },
  empty: { color: colors.muted, fontStyle: 'italic' },
  item: {
    flexDirection: 'row',
    gap: spacing.sm,
    alignItems: 'center',
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  url: { fontWeight: '700', color: colors.text },
  meta: { fontSize: 12, color: colors.textSecondary },
});
