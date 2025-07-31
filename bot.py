import os
import logging
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from supabase import create_client
from datetime import datetime
from flask import Flask, request, jsonify
import asyncio
import threading

# إعداد التسجيل
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# تحميل المتغيرات البيئية فقط إذا لم تكن في بيئة Render
if os.getenv("RENDER") != "true":
    load_dotenv()

# إعداد Supabase
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")

logger.info(f"SUPABASE_URL: {supabase_url}")
logger.info(f"SUPABASE_KEY: {supabase_key}")

# تحقق من وجود المتغيرات البيئية
if not supabase_url or not supabase_key:
    logger.error("SUPABASE_URL أو SUPABASE_KEY غير موجود في متغيرات البيئة.")
    raise ValueError("SUPABASE_URL أو SUPABASE_KEY غير موجود في متغيرات البيئة")

supabase = create_client(supabase_url, supabase_key)

# معرف الأدمن
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))

# إعداد Flask
app = Flask(__name__)

class TelegramBot:
    def __init__(self):
        self.bot_token = os.getenv("BOT_TOKEN")
        if not self.bot_token:
            raise ValueError("BOT_TOKEN غير موجود في متغيرات البيئة")
        self.application = None

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """معالج أمر /start"""
        user = update.effective_user
        
        # التحقق من وجود المستخدم في قاعدة البيانات
        try:
            response = supabase.table("users").select("*").eq("telegram_id", user.id).execute()
            
            if response.data:
                # المستخدم موجود، التحقق من حالة التفعيل
                user_id = response.data[0]["id"]
                activation_response = supabase.table("user_activations").select("*").eq("user_id", user_id).execute()
                
                if activation_response.data and activation_response.data[0]["is_active"]:
                    await update.message.reply_text(
                        f"مرحباً {user.first_name}! 🎉\n"
                        "حسابك مفعل بالفعل ويمكنك الوصول إلى الاختبارات."
                    )
                else:
                    await update.message.reply_text(
                        f"مرحباً {user.first_name}! 👋\n"
                        "حسابك مسجل لكنه غير مفعل حالياً.\n"
                        "يرجى انتظار موافقة الأدمن على تفعيل حسابك."
                    )
            else:
                await update.message.reply_text(
                    f"مرحباً {user.first_name}! 👋\n"
                    "لم يتم العثور على حسابك في النظام.\n"
                    "يرجى تسجيل الدخول أولاً من خلال الموقع الإلكتروني."
                )
                
        except Exception as e:
            logger.error(f"خطأ في معالج start: {e}")
            await update.message.reply_text(
                "حدث خطأ أثناء التحقق من حسابك. يرجى المحاولة لاحقاً."
            )

    async def admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """لوحة تحكم الأدمن"""
        user = update.effective_user
        
        if user.id != ADMIN_USER_ID:
            await update.message.reply_text("غير مصرح لك بالوصول إلى لوحة التحكم.")
            return
        
        keyboard = [
            [InlineKeyboardButton("عرض المستخدمين غير المفعلين", callback_data="show_inactive")],
            [InlineKeyboardButton("عرض جميع المستخدمين", callback_data="show_all")],
            [InlineKeyboardButton("إحصائيات", callback_data="stats")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "🔧 لوحة تحكم الأدمن\n"
            "اختر العملية المطلوبة:",
            reply_markup=reply_markup
        )

    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """معالج الأزرار"""
        query = update.callback_query
        await query.answer()
        
        user = query.from_user
        if user.id != ADMIN_USER_ID:
            await query.edit_message_text("غير مصرح لك بهذه العملية.")
            return
        
        if query.data == "show_inactive":
            await self.show_inactive_users(query)
        elif query.data == "show_all":
            await self.show_all_users(query)
        elif query.data == "stats":
            await self.show_stats(query)
        elif query.data.startswith("activate_"):
            user_id = query.data.split("_")[1]
            await self.activate_user(query, user_id)
        elif query.data.startswith("deactivate_"):
            user_id = query.data.split("_")[1]
            await self.deactivate_user(query, user_id)

    async def show_inactive_users(self, query) -> None:
        """عرض المستخدمين غير المفعلين"""
        try:
            # جلب المستخدمين غير المفعلين
            response = supabase.table("users").select(
                "id, telegram_id, username, created_at, user_activations(is_active)"
            ).eq("user_activations.is_active", False).execute()
            
            if not response.data:
                await query.edit_message_text("لا يوجد مستخدمين غير مفعلين.")
                return
            
            message = "👥 المستخدمين غير المفعلين:\n\n"
            keyboard = []
            
            for user in response.data:
                message += f"🔸 {user["username"] or "غير محدد"}\n"
                message += f"   ID: {user["telegram_id"]}\n"
                message += f"   تاريخ التسجيل: {user["created_at"][:10]}\n\n"
                
                keyboard.append([
                    InlineKeyboardButton(
                        f"تفعيل {user["username"] or user["telegram_id"]}", 
                        callback_data=f"activate_{user["id"]}"
                    )
                ])
            
            keyboard.append([InlineKeyboardButton("العودة", callback_data="back_to_admin")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"خطأ في عرض المستخدمين غير المفعلين: {e}")
            await query.edit_message_text("حدث خطأ أثناء جلب البيانات.")

    async def show_all_users(self, query) -> None:
        """عرض جميع المستخدمين"""
        try:
            response = supabase.table("users").select(
                "id, telegram_id, username, created_at, user_activations(is_active)"
            ).execute()
            
            if not response.data:
                await query.edit_message_text("لا يوجد مستخدمين مسجلين.")
                return
            
            active_count = 0
            inactive_count = 0
            message = "👥 جميع المستخدمين:\n\n"
            
            for user in response.data:
                is_active = user["user_activations"][0]["is_active"] if user["user_activations"] else False
                status = "✅ مفعل" if is_active else "❌ غير مفعل"
                
                if is_active:
                    active_count += 1
                else:
                    inactive_count += 1
                
                message += f"🔸 {user["username"] or "غير محدد"} - {status}\n"
                message += f"   ID: {user["telegram_id"]}\n"
                message += f"   تاريخ التسجيل: {user["created_at"][:10]}\n\n"
            
            message += f"\n📊 الإحصائيات:\n"
            message += f"✅ المفعلين: {active_count}\n"
            message += f"❌ غير المفعلين: {inactive_count}\n"
            message += f"📈 المجموع: {active_count + inactive_count}"
            
            keyboard = [[InlineKeyboardButton("العودة", callback_data="back_to_admin")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"خطأ في عرض جميع المستخدمين: {e}")
            await query.edit_message_text("حدث خطأ أثناء جلب البيانات.")

    async def show_stats(self, query) -> None:
        """عرض الإحصائيات"""
        try:
            # جلب إحصائيات المستخدمين
            all_users = supabase.table("users").select("id").execute()
            active_users = supabase.table("user_activations").select("user_id").eq("is_active", True).execute()
            
            total_users = len(all_users.data) if all_users.data else 0
            active_count = len(active_users.data) if active_users.data else 0
            inactive_count = total_users - active_count
            
            message = "📊 إحصائيات النظام:\n\n"
            message += f"👥 إجمالي المستخدمين: {total_users}\n"
            message += f"✅ المستخدمين المفعلين: {active_count}\n"
            message += f"❌ المستخدمين غير المفعلين: {inactive_count}\n"
            
            if total_users > 0:
                activation_rate = (active_count / total_users) * 100
                message += f"📈 معدل التفعيل: {activation_rate:.1f}%"
            
            keyboard = [[InlineKeyboardButton("العودة", callback_data="back_to_admin")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"خطأ في عرض الإحصائيات: {e}")
            await query.edit_message_text("حدث خطأ أثناء جلب الإحصائيات.")

    async def activate_user(self, query, user_id: str) -> None:
        """تفعيل مستخدم"""
        try:
            # تحديث حالة التفعيل
            response = supabase.table("user_activations").update({
                "is_active": True,
                "activated_by": str(query.from_user.id),
                "activated_at": datetime.now().isoformat()
            }).eq("user_id", user_id).execute()
            
            if response.data:
                # جلب معلومات المستخدم للإشعار
                user_response = supabase.table("users").select("telegram_id, username").eq("id", user_id).execute()
                
                if user_response.data:
                    user_data = user_response.data[0]
                    
                    # إرسال إشعار للمستخدم
                    try:
                        await query.bot.send_message(
                            chat_id=user_data["telegram_id"],
                            text="🎉 تهانينا! تم تفعيل حسابك بنجاح.\n"
                                 "يمكنك الآن الوصول إلى جميع الاختبارات."
                        )
                    except Exception as e:
                        logger.warning(f"لم يتم إرسال الإشعار للمستخدم {user_data["telegram_id"]}: {e}")
                    
                    await query.edit_message_text(
                        f"✅ تم تفعيل المستخدم {user_data["username"] or user_data["telegram_id"]} بنجاح!"
                    )
                else:
                    await query.edit_message_text("تم التفعيل لكن لم يتم العثور على بيانات المستخدم.")
            else:
                await query.edit_message_text("فشل في تفعيل المستخدم.")
                
        except Exception as e:
            logger.error(f"خطأ في تفعيل المستخدم: {e}")
            await query.edit_message_text("حدث خطأ أثناء تفعيل المستخدم.")

    async def deactivate_user(self, query, user_id: str) -> None:
        """إلغاء تفعيل مستخدم"""
        try:
            response = supabase.table("user_activations").update({
                "is_active": False,
                "activated_by": None,
                "activated_at": None
            }).eq("user_id", user_id).execute()
            
            if response.data:
                await query.edit_message_text("❌ تم إلغاء تفعيل المستخدم بنجاح!")
            else:
                await query.edit_message_text("فشل في إلغاء تفعيل المستخدم.")
                
        except Exception as e:
            logger.error(f"خطأ في إلغاء تفعيل المستخدم: {e}")
            await query.edit_message_text("حدث خطأ أثناء إلغاء تفعيل المستخدم.")

    async def setup_bot(self):
        """إعداد البوت"""
        self.application = Application.builder().token(self.bot_token).build()
        
        # إضافة المعالجات
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("admin", self.admin_panel))
        self.application.add_handler(CallbackQueryHandler(self.button_handler))
        
        # تهيئة البوت
        await self.application.initialize()
        # لا تقم بتشغيل start() هنا إذا كنت تستخدم webhooks
        # await self.application.start()
        
        logger.info("تم إعداد البوت بنجاح")

    async def stop_bot(self):
        """إيقاف البوت"""
        if self.application:
            await self.application.stop()
            await self.application.shutdown()

# إنشاء مثيل البوت
bot_instance = TelegramBot()

# Flask routes
@app.route("/")
def health_check():
    return jsonify({"status": "Bot is running", "message": "Telegram bot is active"})

@app.route("/health")
def health():
    return jsonify({"status": "healthy"})

@app.route("/webhook", methods=["POST"])
def webhook():
    """معالج webhook للتليجرام"""
    try:
        # تأكد من أن البوت مهيأ قبل معالجة التحديثات
        if not bot_instance.application:
            asyncio.run(bot_instance.setup_bot())

        update = Update.de_json(request.get_json(), bot_instance.application.bot)
        asyncio.create_task(bot_instance.application.process_update(update))
        return jsonify({"status": "ok"})
    except Exception as e:
        logger.error(f"خطأ في webhook: {e}")
        return jsonify({"error": str(e)}), 500

def run_bot_polling():
    """تشغيل البوت في وضع polling (للتطوير المحلي فقط)"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    async def start_polling():
        await bot_instance.setup_bot()
        await bot_instance.application.updater.start_polling()
        await bot_instance.application.updater.idle()
    
    try:
        loop.run_until_complete(start_polling())
    except Exception as e:
        logger.error(f"خطأ في تشغيل البوت (polling): {e}")
    finally:
        loop.close()

if __name__ == "__main__":
    try:
        # في بيئة الإنتاج (مثل Render)، استخدم webhooks
        # في بيئة التطوير المحلية، يمكنك استخدام polling
        if os.getenv("RENDER") == "true": # افتراض أن Render يحدد هذا المتغير
            # إعداد البوت لـ webhooks
            asyncio.run(bot_instance.setup_bot())
            logger.info("البوت جاهز لاستقبال webhooks.")
            
            # تشغيل Flask server
            port = int(os.environ.get("PORT", 5000))
            app.run(host="0.0.0.0", port=port, debug=False)
        else:
            # تشغيل البوت في thread منفصل لـ polling (للتطوير المحلي)
            bot_thread = threading.Thread(target=run_bot_polling, daemon=True)
            bot_thread.start()
            
            # تشغيل Flask server (يمكن استخدامه لـ health checks)
            port = int(os.environ.get("PORT", 5000))
            app.run(host="0.0.0.0", port=port, debug=True) # debug=True للتطوير
            
    except Exception as e:
        logger.error(f"خطأ في تشغيل التطبيق: {e}")
    finally:
        # تنظيف الموارد عند الإغلاق
        if bot_instance.application and not os.getenv("RENDER") == "true":
            asyncio.run(bot_instance.stop_bot())



