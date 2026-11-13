// Development-only harness: actual ReviewRoom, isolated API/database, never a business list.
import ReactDOM from 'react-dom/client'
import {ReviewRoom} from '../App'
import {api} from '../backend-api'
import '../styles.css'
if(!import.meta.env.DEV)throw Error('验证入口仅在开发环境可用')
const id=new URLSearchParams(location.search).get('id')
const c=await api<any>(`/contracts/${id}`)
if(c.data_purpose!=='test')throw Error('验证入口仅接受测试合同')
const item={...c.client_metadata,id:'server:'+c.id,title:c.title,position:c.our_party,hasDocument:true,example:false}
ReactDOM.createRoot(document.getElementById('root')!).render(<ReviewRoom item={item} onBack={()=>location.href='/'} onRules={()=>location.href='/'}/>)
