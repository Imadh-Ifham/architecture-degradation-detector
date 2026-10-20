/**
 * The API surface, in one import.
 *
 * Description:
 *   One module per area of the backend, re-exported here so a screen imports
 *   from `lib/api` and never from a path that says how the backend is
 *   organised. A route that moves is a change in one file.
 *
 *   When an area of the system grows its own endpoints, it gets its own module
 *   beside these and one line here. Nothing else changes.
 */

export * from './client'
export * from './degradation'
export * from './repositories'
export * from './server'
export * from './validation'
