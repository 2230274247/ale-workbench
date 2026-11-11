import { createRouter, createWebHistory } from 'vue-router'
import { useAuth } from './auth'
export const router=createRouter({history:createWebHistory(),routes:[
 {path:'/login',component:()=>import('./views/LoginView.vue'),meta:{public:true}},
 {path:'/m',component:()=>import('./mobile/MobileShell.vue'),children:[
 {path:'',name:'mobile-home',redirect:'/m/quick'},
 {path:'quick',component:()=>import('./mobile/MobileQuickView.vue'),meta:{title:'实验快录'}},
 {path:'history',component:()=>import('./mobile/MobileHistoryView.vue'),meta:{title:'实验历史'}},
 {path:'dataset',component:()=>import('./mobile/MobileDatasetView.vue'),meta:{title:'数据集'}},
 {path:'me',component:()=>import('./mobile/MobileMeView.vue'),meta:{title:'我的'}}
 ]},
 {path:'/m/login',component:()=>import('./views/LoginView.vue'),meta:{public:true}},
 {path:'/',component:()=>import('./components/AppShell.vue'),children:[
 {path:'',name:'home',redirect:'/quick'},
 {path:'quick',component:()=>import('./views/QuickRecordView.vue'),meta:{title:'实验快录'}},
 {path:'quick-history',component:()=>import('./views/QuickDatasetView.vue'),meta:{title:'实验历史'}},
 {path:'quick-dataset',component:()=>import('./views/QuickDatasetView.vue'),meta:{title:'数据集中心'}},
 {path:'quick-lab',component:()=>import('./views/QuickDatasetView.vue'),meta:{title:'AI 实验室'}},
 {path:'quick-templates',component:()=>import('./views/QuickTemplatesView.vue'),meta:{title:'工艺模板'}},
 {path:'professional',component:()=>import('./views/DashboardView.vue'),meta:{title:'专业模式'}} ,
 {path:'batches',component:()=>import('./views/RecordsView.vue'),props:{kind:'batches'},meta:{title:'批次管理'}},
 {path:'samples',component:()=>import('./views/RecordsView.vue'),props:{kind:'samples'},meta:{title:'样品管理'}},
 {path:'experiments/new',component:()=>import('./views/ExperimentWizardView.vue'),meta:{title:'开始新实验'}},
 {path:'plans',component:()=>import('./views/ExperimentPlansView.vue'),meta:{title:'实验计划'}},
 {path:'processes',component:()=>import('./views/ProcessesView.vue'),meta:{title:'实验执行'}},
 {path:'sample-history',component:()=>import('./views/SampleHistoryView.vue'),meta:{title:'样品科研履历'}},
 {path:'imports',component:()=>import('./views/ImportsView.vue'),meta:{title:'统一导入中心'}},
 {path:'analysis',component:()=>import('./views/AnalysisView.vue'),meta:{title:'科研分析'}},
 {path:'measurements',component:()=>import('./views/MeasurementsView.vue'),meta:{title:'正式测量'}},
 {path:'source-files',component:()=>import('./views/SourceFilesView.vue'),meta:{title:'原始文件档案'}},
 {path:'instruments/:type',component:()=>import('./views/InstrumentsView.vue'),meta:{title:'仪器数据'}},
 {path:'chemistry',component:()=>import('./views/ChemistryView.vue'),meta:{title:'化学体系'}},
 {path:'ai-settings',component:()=>import('./views/AISettingsView.vue'),meta:{title:'AI 设置',admin:true}},
 {path:'users',component:()=>import('./views/UsersView.vue'),meta:{title:'成员与邀请',admin:true}}
 ]}, {path:'/:pathMatch(.*)*',redirect:'/'}]})
router.beforeEach(async(to)=>{const auth=useAuth();await auth.restore();const mobile=to.path.startsWith('/m');if(!to.meta.public&&!auth.user)return mobile?'/m/login':'/login';if(to.meta.admin&&!auth.isAdmin)return '/';if((to.path==='/login'||to.path==='/m/login')&&auth.user)return mobile?'/m/quick':'/'})


