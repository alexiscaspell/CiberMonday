import React from 'react';
import {
  ActivityIndicator,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  ViewStyle,
} from 'react-native';
import { colors, radius, spacing } from '../theme';

type Variant = 'primary' | 'danger' | 'secondary' | 'success' | 'ghost';

interface Props {
  title: string;
  onPress: () => void;
  variant?: Variant;
  disabled?: boolean;
  loading?: boolean;
  style?: ViewStyle;
  compact?: boolean;
}

const bg: Record<Variant, string> = {
  primary: colors.primary,
  danger: colors.danger,
  secondary: colors.muted,
  success: colors.success,
  ghost: 'transparent',
};

export function Button({
  title,
  onPress,
  variant = 'primary',
  disabled,
  loading,
  style,
  compact,
}: Props) {
  const isGhost = variant === 'ghost';
  const busy = disabled || loading;

  // Android WebView: Pressable/onPress a menudo no dispara; usar <button> nativo.
  if (Platform.OS === 'web') {
    const flat = StyleSheet.flatten([
      styles.base,
      compact && styles.compact,
      { backgroundColor: bg[variant], opacity: busy ? 0.7 : 1 },
      isGhost && styles.ghost,
      style,
    ]) as Record<string, unknown>;

    return React.createElement(
      'button',
      {
        type: 'button',
        disabled: busy,
        onClick: (e: { preventDefault: () => void; stopPropagation: () => void }) => {
          e.preventDefault();
          e.stopPropagation();
          if (!busy) onPress();
        },
        'aria-label': title,
        style: {
          ...flat,
          border: isGhost ? `1px solid ${colors.border}` : 'none',
          cursor: busy ? 'default' : 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontFamily: 'inherit',
        },
      },
      loading
        ? React.createElement(ActivityIndicator, {
            color: isGhost ? colors.primary : '#fff',
          })
        : React.createElement(
            Text,
            { style: [styles.label, isGhost && styles.ghostLabel] },
            title,
          ),
    );
  }

  return (
    <Pressable
      onPress={onPress}
      disabled={busy}
      accessibilityRole="button"
      style={({ pressed }) => [
        styles.base,
        compact && styles.compact,
        { backgroundColor: bg[variant], opacity: pressed || busy ? 0.7 : 1 },
        isGhost && styles.ghost,
        style,
      ]}
    >
      {loading ? (
        <ActivityIndicator color={isGhost ? colors.primary : '#fff'} />
      ) : (
        <Text style={[styles.label, isGhost && styles.ghostLabel]}>{title}</Text>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  base: {
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.sm,
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: 44,
  },
  compact: {
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    minHeight: 36,
  },
  ghost: {
    borderWidth: 1,
    borderColor: colors.border,
  },
  label: {
    color: '#fff',
    fontWeight: '700',
    fontSize: 14,
  },
  ghostLabel: {
    color: colors.primary,
  },
});
