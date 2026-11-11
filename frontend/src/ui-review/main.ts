import { createApp } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import '../style.css'
import './review.css'
import Review from './Review.vue'

// A separate entry, memory router and local fixtures: no auth or API bootstrap.
const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/:pathMatch(.*)*', component: { template: '<div />' } }] })
createApp(Review).use(router).use(ElementPlus, { locale: zhCn }).mount('#app')
