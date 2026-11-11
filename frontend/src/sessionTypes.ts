import type { User, CurrentUser } from './contracts'
export type AccountPurpose = 'management' | 'research' | 'testing'
export type SessionUser = User & { account_purpose?:AccountPurpose }
export interface SessionEnvironment { name:'production'|'testing'; label:string; instance_id:string }
export type SessionCurrentUser = Omit<CurrentUser,'user'> & { user:SessionUser; environment?:SessionEnvironment }
export const purposeNames:Record<AccountPurpose,string> = {management:'管理账户',research:'科研账户',testing:'测试账户'}
