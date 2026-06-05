-- ONE-TIME SETUP: Create firm and user record for your Supabase auth account.
-- Run this in Supabase Dashboard → SQL Editor AFTER logging in to the app at least once.
-- Replace the email below with your actual login email.

DO $$
DECLARE
  v_auth_user_id uuid;
  v_firm_id uuid;
BEGIN
  -- Find your auth user ID by email (replace with your actual email)
  SELECT id INTO v_auth_user_id
  FROM auth.users
  WHERE email = 'gavinlobo730@gmail.com'
  LIMIT 1;

  IF v_auth_user_id IS NULL THEN
    RAISE EXCEPTION 'Auth user not found. Make sure you have logged in at least once and the email is correct.';
  END IF;

  -- Check if firm already exists for this user
  SELECT firm_id INTO v_firm_id
  FROM public.users
  WHERE auth_user_id = v_auth_user_id
  LIMIT 1;

  -- Create firm if it doesn't exist
  IF v_firm_id IS NULL THEN
    INSERT INTO public.firms (id, firm_name, created_at, updated_at)
    VALUES (gen_random_uuid(), 'My CA Firm', now(), now())
    RETURNING id INTO v_firm_id;

    -- Create user record linked to the firm
    INSERT INTO public.users (id, auth_user_id, firm_id, full_name, role, email, created_at, updated_at)
    VALUES (
      gen_random_uuid(),
      v_auth_user_id,
      v_firm_id,
      'Gavin Lobo',
      'Partner',
      'gavinlobo730@gmail.com',
      now(),
      now()
    );

    RAISE NOTICE 'Created firm % and user record for %', v_firm_id, v_auth_user_id;
  ELSE
    RAISE NOTICE 'User record already exists with firm_id %', v_firm_id;
  END IF;
END $$;
