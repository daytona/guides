import daytona from '@daytona/convex/convex.config.js'
import { defineApp } from 'convex/server'

const app = defineApp()
app.use(daytona)

export default app
