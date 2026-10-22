import type { Plan } from './api/types'

export type Tier = 'free' | 'pro' | 'ultra' | 'enterprise'

/** Faol pullik tarif (1 soat/1 kun/1 oy... — davridan qat'i nazar) -> premium ko'rinish darajasi. */
export function tierOf(plan: Pick<Plan, 'type' | 'is_pro'> | null | undefined): Tier {
  if (!plan) return 'free'
  if (plan.type === 'ultra') return 'ultra'
  if (plan.type === 'enterprise') return 'enterprise'
  return plan.is_pro ? 'pro' : 'free'
}

export const isPremium = (tier: Tier): boolean => tier !== 'free'
