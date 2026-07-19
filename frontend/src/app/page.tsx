'use client'
import { useEffect } from 'react'
import { useRouter } from 'next/navigation'

export const dynamic = 'force-dynamic'

export default function Home() {
  const router = useRouter()
  useEffect(() => {
    const token = localStorage.getItem('etair_token')
    router.replace(token ? '/dashboard' : '/login')
  }, [router])
  return null
}
