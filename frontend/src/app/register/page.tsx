'use client'
import { useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'

export const dynamic = 'force-dynamic'
import { authApi } from '@/lib/api'
import { Zap, Eye, EyeOff, Loader2, AlertCircle, CheckCircle2 } from 'lucide-react'

export default function RegisterPage() {
  const router = useRouter()
  const [form, setForm] = useState({ email: '', password: '', full_name: '' })
  const [showPass, setShowPass] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setError('')
    if (form.password.length < 8) {
      setError('Password must be at least 8 characters.')
      return
    }
    if (new TextEncoder().encode(form.password).length > 72) {
      setError('Password is too long (max 72 characters).')
      return
    }
    setLoading(true)
    try {
      const res = await authApi.register(form)
      localStorage.setItem('etair_token', res.data.access_token)
      localStorage.setItem('etair_user', JSON.stringify({
        user_id: res.data.user_id,
        email: res.data.email,
        full_name: res.data.full_name,
      }))
      router.push('/dashboard')
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Registration failed.')
    } finally {
      setLoading(false)
    }
  }

  const passwordStrength = () => {
    const p = form.password
    if (!p) return null
    if (p.length < 8) return { label: 'Too short', color: 'text-red-400', bars: 1 }
    if (p.length < 12) return { label: 'Moderate', color: 'text-amber-400', bars: 2 }
    return { label: 'Strong', color: 'text-emerald-400', bars: 3 }
  }
  const strength = passwordStrength()

  return (
    <div className="min-h-screen bg-surface-0 bg-mesh flex items-center justify-center p-4">
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute top-1/4 left-1/2 -translate-x-1/2 w-[600px] h-[600px] bg-brand-600/10 rounded-full blur-3xl" />
      </div>

      <div className="relative w-full max-w-md animate-slide-up">
        <div className="text-center mb-8">
          <div className="inline-flex items-center gap-2 mb-4">
            <div className="w-10 h-10 rounded-xl bg-gradient-brand flex items-center justify-center shadow-glow">
              <Zap className="w-5 h-5 text-white" strokeWidth={2.5} />
            </div>
            <span className="text-2xl font-bold text-gradient">ETAIR</span>
          </div>
          <h1 className="text-xl font-semibold text-white">Create your account</h1>
          <p className="text-muted text-sm mt-1">Join your team's industrial knowledge workspace</p>
        </div>

        <div className="card border-border/60 shadow-glow-sm">
          <form onSubmit={handleRegister} className="space-y-4">
            {error && (
              <div className="flex items-start gap-2 bg-red-900/20 border border-red-800/40 rounded-lg p-3">
                <AlertCircle className="w-4 h-4 text-red-400 mt-0.5 flex-shrink-0" />
                <p className="text-sm text-red-300">{error}</p>
              </div>
            )}

            <div>
              <label htmlFor="full_name" className="label">Full name</label>
              <input
                id="full_name"
                type="text"
                value={form.full_name}
                onChange={e => setForm({ ...form, full_name: e.target.value })}
                placeholder="John Smith"
                className="input"
                required
                autoFocus
              />
            </div>

            <div>
              <label htmlFor="email" className="label">Work email</label>
              <input
                id="email"
                type="email"
                value={form.email}
                onChange={e => setForm({ ...form, email: e.target.value })}
                placeholder="engineer@plant.com"
                className="input"
                required
              />
            </div>

            <div>
              <label htmlFor="password" className="label">Password</label>
              <div className="relative">
                <input
                  id="password"
                  type={showPass ? 'text' : 'password'}
                  value={form.password}
                  onChange={e => setForm({ ...form, password: e.target.value })}
                  placeholder="Min. 8 characters"
                  className="input pr-10"
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPass(!showPass)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-muted hover:text-white transition-colors"
                >
                  {showPass ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
              {strength && (
                <div className="mt-2 flex items-center gap-2">
                  <div className="flex gap-1">
                    {[1, 2, 3].map(i => (
                      <div
                        key={i}
                        className={`h-1 w-8 rounded-full transition-all ${
                          i <= strength.bars
                            ? strength.bars === 1 ? 'bg-red-500' : strength.bars === 2 ? 'bg-amber-500' : 'bg-emerald-500'
                            : 'bg-border'
                        }`}
                      />
                    ))}
                  </div>
                  <span className={`text-xs ${strength.color}`}>{strength.label}</span>
                </div>
              )}
            </div>

            <button
              type="submit"
              disabled={loading}
              className="btn-primary w-full justify-center py-2.5"
            >
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle2 className="w-4 h-4" />}
              {loading ? 'Creating account…' : 'Create account'}
            </button>
          </form>

          <div className="mt-6 pt-6 border-t border-border text-center">
            <p className="text-sm text-muted">
              Already have an account?{' '}
              <Link href="/login" className="text-brand-400 hover:text-brand-300 font-medium transition-colors">
                Sign in
              </Link>
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
