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
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled || loading}
      accessibilityRole="button"
      style={({ pressed }) => [
        styles.base,
        compact && styles.compact,
        { backgroundColor: bg[variant], opacity: pressed || disabled ? 0.7 : 1 },
        isGhost && styles.ghost,
        Platform.OS === 'web' ? ({ cursor: disabled ? 'default' : 'pointer' } as object) : null,
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
