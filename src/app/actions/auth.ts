'use server'

import { revalidatePath } from 'next/cache'
import { redirect } from 'next/navigation'
import { createClient } from '@/utils/supabase/server'

import { cookies } from 'next/headers'

export async function login(formData: FormData) {
  const email = formData.get('email') as string;
  const password = formData.get('password') as string;

  if (!email || !password) {
    return { error: 'Please submit both an email and a password.' }
  }

  // Temporary local mock override for auth while Supabase isn't synced
  const cookieStore = await cookies()
  cookieStore.set('sawa_auth_token', 'mock_jwt_token_12345', {
    path: '/',
    maxAge: 86400,
    sameSite: 'lax',
  })

  revalidatePath('/dashboard', 'layout')
  redirect('/dashboard')
}

export async function logout() {
  // Temporary local mock override for auth while Supabase isn't synced
  const cookieStore = await cookies();
  cookieStore.delete('sawa_auth_token');

  revalidatePath('/', 'layout')
  redirect('/login')
}
